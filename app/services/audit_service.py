"""
The atomic AuditEvent helper (Epic 1, step 3 — built right after migrations,
before Auth/Membership or anything else, so every later feature has this to
call from day one instead of bolting audit logging on at the end).

Usage — every mutating operation in the app should look like this:

    from app.services.audit_service import audited_transaction

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=current_user.id,
    ) as audit:
        shift.status = ShiftStatus.cancelled
        session.add(shift)
        audit.record(
            action="shift.cancelled",
            entity_type="shift",
            entity_id=shift.id,
            before={"status": "published"},
            after={"status": "cancelled"},
        )
    # both the Shift update and the AuditEvent commit together here, or
    # neither does — audited_transaction only calls session.commit() once,
    # after the `with` block exits without raising.

If the block raises, the session is rolled back and the exception re-raised:
nothing the block touched is persisted, mutation or audit event alike.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent


class _AuditRecorder:
    """Handed to the caller inside the `with` block. `.record()` stages an
    AuditEvent on the session — it does NOT commit. The transaction context
    manager owns the single commit/rollback for the whole block."""

    def __init__(
        self,
        session: Session,
        *,
        organisation_id: uuid.UUID,
        venue_id: uuid.UUID,
        service_day_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
    ) -> None:
        self._session = session
        self._organisation_id = organisation_id
        self._venue_id = venue_id
        self._service_day_id = service_day_id
        self._actor_user_id = actor_user_id
        self.events: list[AuditEvent] = []

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: Any,
        before: dict | None = None,
        after: dict | None = None,
        service_day_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            organisation_id=self._organisation_id,
            venue_id=self._venue_id,
            service_day_id=service_day_id or self._service_day_id,
            actor_user_id=self._actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before_data=before,
            after_data=after,
        )
        self._session.add(event)
        self.events.append(event)
        return event


@contextmanager
def audited_transaction(
    session: Session,
    *,
    organisation_id: uuid.UUID,
    venue_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    service_day_id: uuid.UUID | None = None,
) -> Iterator[_AuditRecorder]:
    """
    One database transaction: whatever mutation the caller performs inside
    the `with` block, plus every AuditEvent recorded via `.record()`, commit
    together in a single `session.commit()` — or, on any exception, the
    whole block is rolled back and nothing is persisted.
    """
    recorder = _AuditRecorder(
        session,
        organisation_id=organisation_id,
        venue_id=venue_id,
        service_day_id=service_day_id,
        actor_user_id=actor_user_id,
    )
    try:
        yield recorder
        session.commit()
    except Exception:
        session.rollback()
        raise
