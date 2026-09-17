"""
Epic 11 — Metrics wiring checklist (locked spec), the three items that
aren't already covered by an earlier epic's own AuditEvent:
  - brief.opened (Epic 8) and handover.saved (Epic 7, now carrying
    opened_at/closed_at — see this epic's own audit-coverage pass) exist
    already; PurchaseOrder "sent" now carries `sources` too (see
    supplier_order_service.send_purchase_order).
  - "Weekly self-reported 'minutes saved' prompt to the Head Chef",
    "Missed-order/handover-failure incidents logged manually ... tagged to
    the relevant ServiceDay", and "Owner's pay-at-proposed-price answer ...
    a single yes/no field at the decision gate" are genuinely new — there's
    no existing mutation to piggyback an AuditEvent onto, since these are
    pilot-tracking data points a person reports directly, not a
    side-effect of some other action.

No new table for any of the three: each is a single AuditEvent — the
"record" IS the event, not a mutation the event describes. This is a
deliberate extension of the same "AuditEvent as the record, not just the
trail" reasoning Epic 2's roster.notification_queued and Epic 10's
dedup-via-AuditEvent already lean on, applied here because these three
data points are genuinely one-shot facts (a survey answer, an incident
report, a decision) rather than anything with its own lifecycle a real
table would need to model.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.service_day_service import get_or_create_service_day

MINUTES_SAVED_ACTION = "metrics.minutes_saved_reported"
INCIDENT_ACTION = "metrics.incident_logged"
PILOT_DECISION_ACTION = "metrics.pilot_decision_recorded"

INCIDENT_TYPES = ("missed_order", "handover_failure")


class InvalidIncidentType(Exception):
    """incident_type must be one of INCIDENT_TYPES — locked AC names
    exactly these two ("missed-order / handover-failure incidents")."""


def record_minutes_saved(
    session: Session, *, venue: Venue, actor: User, week_start: date, minutes_saved: int,
) -> AuditEvent:
    """The weekly self-reported prompt's answer. Keyed by week_start in the
    payload (not a ServiceDay — this is a weekly figure, not a per-day
    one), so a venue can have at most one clean answer per week without
    needing a dedicated table just to enforce that; a re-submission for
    the same week is still logged (a correction is a fact too), not
    silently merged."""
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
    ) as audit:
        event = audit.record(
            action=MINUTES_SAVED_ACTION, entity_type="venue", entity_id=venue.id,
            after={"week_start": week_start.isoformat(), "minutes_saved": minutes_saved},
        )
    return event


def log_incident(
    session: Session, *, venue: Venue, actor: User, business_date: date, incident_type: str, description: str,
) -> AuditEvent:
    """Tagged to the relevant ServiceDay (locked AC) — lazily created on
    first reference, same as every other epic's first operational touch of
    a day, since an incident can be logged after the fact for a day that
    was never otherwise opened via this path (e.g. reported by phone the
    next morning)."""
    if incident_type not in INCIDENT_TYPES:
        raise InvalidIncidentType(f"incident_type must be one of {INCIDENT_TYPES}, got {incident_type!r}")

    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    session.commit()

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        event = audit.record(
            action=INCIDENT_ACTION, entity_type="service_day", entity_id=service_day.id,
            after={"incident_type": incident_type, "description": description},
        )
    return event


def record_pilot_decision(
    session: Session, *, venue: Venue, actor: User, will_pay_at_proposed_price: bool, notes: str | None = None,
) -> AuditEvent:
    """The decision-gate yes/no (locked AC) — owner-only at the route
    layer (app/api/routes/pilot_metrics.py), since this is specifically
    framed as "the Owner's ... answer", not any manager's. Writing it more
    than once is allowed (an owner can change their mind before go-live);
    the LATEST event by recorded_at is the one that counts, same "derived
    current, full history retained" reasoning as AttendanceEvent."""
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
    ) as audit:
        event = audit.record(
            action=PILOT_DECISION_ACTION, entity_type="venue", entity_id=venue.id,
            after={"will_pay_at_proposed_price": will_pay_at_proposed_price, "notes": notes},
        )
    return event


def get_pilot_metrics(session: Session, *, venue: Venue) -> list[AuditEvent]:
    """Every metrics.* event for this venue, oldest first — the raw feed a
    pilot report is built from. No aggregation here (e.g. "total minutes
    saved") since that's a reporting concern, not this service's job."""
    return (
        session.query(AuditEvent)
        .filter(
            AuditEvent.venue_id == venue.id,
            AuditEvent.action.in_((MINUTES_SAVED_ACTION, INCIDENT_ACTION, PILOT_DECISION_ACTION)),
        )
        .order_by(AuditEvent.recorded_at)
        .all()
    )
