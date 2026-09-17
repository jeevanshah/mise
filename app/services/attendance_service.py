"""
Epic 3 — Attendance & Coverage.

AttendanceEvent is append-only: nothing here ever updates or deletes a row.
"Current attendance" for a Shift is always a derived read (the latest event
by recorded_at — see get_current_status), never a stored column, so the
full history and the "current" view can never drift apart.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.attendance import AttendanceEvent, AttendanceSource, AttendanceStatus
from app.models.roster import Shift
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.roster_service import resolve_staff_link


class DuplicateStaffCheckIn(Exception):
    """A Staff member logs exactly one AttendanceEvent for their own Shift
    via the signed link (locked AC) — a second attempt is rejected rather
    than silently appending another self-report. A chef can still log as
    many corrections as needed; this restriction is staff_link-only."""


def _record(
    session: Session, *, venue: Venue, shift: Shift, status: AttendanceStatus,
    source: AttendanceSource, actor_user_id, note: str | None,
) -> AttendanceEvent:
    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor_user_id,
        service_day_id=shift.service_day_id,
    ) as audit:
        event = AttendanceEvent(
            shift_id=shift.id,
            status=status,
            source=source,
            actor_user_id=actor_user_id,
            note=note,
            recorded_at=datetime.now(timezone.utc),
        )
        session.add(event)
        session.flush()
        audit.record(
            action="attendance_event.logged",
            entity_type="attendance_event",
            entity_id=event.id,
            after={
                "shift_id": str(shift.id),
                "status": status.value,
                "source": source.value,
                "note": note,
            },
        )
    return event


def log_attendance_as_chef(
    session: Session, *, venue: Venue, actor: User, shift: Shift,
    status: AttendanceStatus, note: str | None = None,
) -> AttendanceEvent:
    """No cap on how many times a chef can log — each one is a new,
    retained event; the latest by recorded_at is what displays."""
    return _record(
        session, venue=venue, shift=shift, status=status,
        source=AttendanceSource.chef, actor_user_id=actor.id, note=note,
    )


def log_attendance_via_link(
    session: Session, *, raw_token: str, status: AttendanceStatus, note: str | None = None
) -> AttendanceEvent:
    shift, staff = resolve_staff_link(session, raw_token=raw_token)
    venue = session.get(Venue, shift.venue_id)

    already_checked_in = (
        session.query(AttendanceEvent)
        .filter_by(shift_id=shift.id, source=AttendanceSource.staff_link)
        .first()
    )
    if already_checked_in is not None:
        raise DuplicateStaffCheckIn(f"{staff.name} has already checked in for this shift")

    return _record(
        session, venue=venue, shift=shift, status=status,
        source=AttendanceSource.staff_link, actor_user_id=None, note=note,
    )


def get_current_status(session: Session, *, shift: Shift) -> AttendanceStatus | None:
    """None means "expected" — no AttendanceEvent has ever been logged."""
    latest = (
        session.query(AttendanceEvent)
        .filter_by(shift_id=shift.id)
        .order_by(AttendanceEvent.recorded_at.desc(), AttendanceEvent.created_at.desc())
        .first()
    )
    return latest.status if latest is not None else None


def list_attendance_history(session: Session, *, shift: Shift) -> list[AttendanceEvent]:
    return (
        session.query(AttendanceEvent)
        .filter_by(shift_id=shift.id)
        .order_by(AttendanceEvent.recorded_at)
        .all()
    )
