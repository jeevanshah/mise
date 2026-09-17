"""
Epic 1 step 8 — ServiceDay lifecycle: business_date resolution, lazy
creation, and the audited planned -> open transition. See
app/models/service_day.py's docstring for the AC this implements.

Nothing in Epic 1 itself calls get_or_create_service_day as part of a
larger operational write yet (Shift/PrepTask etc. are Epic 2+) — the two
HTTP endpoints in app/api/routes/service_days.py exist to prove this
plumbing end-to-end now, so later epics have a tested foundation to call
into rather than a function nobody has exercised outside unit tests.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.service_day import ServiceDay, ServiceDayStatus
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class CannotOpenClosedServiceDay(Exception):
    """A closed ServiceDay is reopened only through the explicit, audited
    "reopen day" action (Epic 7) — never silently reopened as a side
    effect of calling this again."""


class ServiceDayIsClosed(Exception):
    """A closed ServiceDay's PrepTasks/Captures are read-only (Epic 7
    locked AC). New rows can still be added via the sanctioned
    "added after close" late-entry path (app/services/prep_service.py,
    app/services/capture_service.py); everything else — new tasks/captures
    without that flag, and any edit to an existing one — is rejected until
    the day is explicitly reopened (app/services/handover_service.py)."""


def resolve_business_date(venue: Venue, at: datetime | None = None) -> date:
    """business_date is NOT the calendar date. Hours before
    Venue.business_day_boundary belong to the PRIOR business date — e.g. a
    Friday dinner service ending 1am Saturday is still business_date =
    Friday, with the default 04:00 boundary, because 1am < 04:00."""
    moment = at if at is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("resolve_business_date requires a timezone-aware datetime")

    local_moment = moment.astimezone(ZoneInfo(venue.timezone))
    if local_moment.time() < venue.business_day_boundary:
        return (local_moment - timedelta(days=1)).date()
    return local_moment.date()


def get_or_create_service_day(session: Session, *, venue: Venue, business_date: date) -> ServiceDay:
    """Lazy creation: call this whenever a ServiceDay is first referenced by
    ANY operational write (a Shift ten days out, a scheduled notification,
    ...) — not only when someone opens the app on that date. Idempotent:
    two calls for the same (venue, business_date) return the same row.
    Does not commit — same "flush now, let the caller's audited_transaction
    commit everything together" pattern as onboarding_service, since this
    is meant to be called as one step inside some larger mutation."""
    existing = (
        session.query(ServiceDay)
        .filter_by(venue_id=venue.id, business_date=business_date)
        .one_or_none()
    )
    if existing is not None:
        return existing

    service_day = ServiceDay(venue_id=venue.id, business_date=business_date)
    session.add(service_day)
    session.flush()
    return service_day


def open_service_day(
    session: Session, *, service_day: ServiceDay, venue: Venue, actor: User
) -> ServiceDay:
    """planned -> open. Idempotent: already-open returns the same row
    without writing a second AuditEvent. Raises CannotOpenClosedServiceDay
    for a closed day rather than silently reopening it."""
    if service_day.status == ServiceDayStatus.open:
        return service_day
    if service_day.status == ServiceDayStatus.closed:
        raise CannotOpenClosedServiceDay(
            "Use the explicit reopen-day action (Epic 7) to reopen a closed ServiceDay"
        )

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        service_day.status = ServiceDayStatus.open
        service_day.opened_at = datetime.now(timezone.utc)
        session.add(service_day)
        session.flush()
        audit.record(
            action="service_day.opened",
            entity_type="service_day",
            entity_id=service_day.id,
            before={"status": "planned"},
            after={"status": "open"},
        )

    return service_day
