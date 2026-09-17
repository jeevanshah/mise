"""
Epic 10 — Operational Email Notifications (chef-facing checks).

Staff-facing notifications (locked AC: "limited strictly to their own
published/cancelled Shifts and roster-publish notices") are wired directly
into roster_service.publish_shift/cancel_shift — there's no periodic check
for those, they fire exactly when the triggering action happens. This
module is the OTHER half: the three chef-facing triggers, which genuinely
have to be checked against the current time rather than reacting to a
single mutation —

  - order cut-off approaching (reuses Epic 8's own
    chef_brief_service.compute_approaching_cutoffs — the identical
    computation, just emailed instead of only shown in the Brief)
  - unfilled Shift within 48h (reuses Epic 2's compute_coverage_warnings,
    scanning the business dates the next 48h could fall into)
  - EquipmentIssue open >24h (reuses Epic 7's
    handover_service.get_open_equipment_issues)

Every send goes through email_service.send_email — the one pluggable hook
in the system (locked AC: "email only"). Recipients are every
MANAGEMENT_ROLES Membership at the venue, matching every other
"chef-level decision" recipient set in this codebase.

Dedup ("no duplicate notification for the same trigger within the same
ServiceDay", locked AC) is done against the AuditEvent trail itself rather
than a new table: each trigger's own AuditEvent — keyed by
(action, entity_type, entity_id, service_day_id) — IS the record of "this
was already sent today." This generalizes Epic 2's own
"roster.notification_queued AuditEvent as the notification record" pattern
and matches Epic 9's general preference for the simplest mechanism that's
actually correct over new schema — no Notification table needed.

run_notification_checks is the single entry point a scheduler would call
per venue. There is no scheduler/cron in this backend build (see its own
HTTP route's docstring for how it's exposed instead). It's public and
takes an explicit `as_of` — mirroring compute_coverage_warnings and
compute_approaching_cutoffs — so it's deterministically testable instead
of only through the real wall clock.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.equipment import EquipmentItem
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.chef_brief_service import compute_approaching_cutoffs
from app.services.email_service import send_email
from app.services.handover_service import get_open_equipment_issues
from app.services.roster_service import compute_coverage_warnings
from app.services.service_day_service import get_or_create_service_day, resolve_business_date

# Not spec-mandated beyond "approaching"/"within"/">" — chosen the same way
# chef_brief_service.APPROACHING_CUTOFF_WINDOW was: wide enough that a chef
# checking once still has time to act, narrow enough to stay meaningful.
UNFILLED_SHIFT_WINDOW = timedelta(hours=48)
STALE_EQUIPMENT_ISSUE_THRESHOLD = timedelta(hours=24)

ORDER_CUTOFF_ACTION = "notification.order_cutoff_approaching"
UNFILLED_SHIFT_ACTION = "notification.unfilled_shift"
STALE_EQUIPMENT_ACTION = "notification.equipment_issue_stale"

# Same three roles as app.api.deps.MANAGEMENT_ROLES, duplicated here rather
# than imported — app.api.deps sits above the service layer (it imports
# app.services.auth_service), and importing back down from a service would
# invert that direction. Keep in sync if the role set ever changes.
_MANAGEMENT_ROLES = (MembershipRole.owner, MembershipRole.ops_manager, MembershipRole.head_chef)


@dataclass
class SentNotification:
    action: str
    entity_type: str
    entity_id: uuid.UUID
    recipients: list[str]
    subject: str


def _management_emails(session: Session, *, venue: Venue) -> list[str]:
    rows = (
        session.query(User.email)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.venue_id == venue.id, Membership.role.in_(_MANAGEMENT_ROLES))
        .all()
    )
    return [email for (email,) in rows]


def _already_sent_today(
    session: Session, *, action: str, entity_type: str, entity_id: uuid.UUID, service_day_id: uuid.UUID
) -> bool:
    return session.query(
        session.query(AuditEvent)
        .filter_by(
            action=action, entity_type=entity_type, entity_id=str(entity_id), service_day_id=service_day_id,
        )
        .exists()
    ).scalar()


def _notify_management(
    session: Session, *, venue: Venue, service_day_id: uuid.UUID,
    action: str, entity_type: str, entity_id: uuid.UUID, subject: str, body: str,
) -> SentNotification | None:
    """Sends subject/body to every MANAGEMENT_ROLES member at the venue and
    records exactly one AuditEvent for the trigger — or does nothing at all
    (no email, no AuditEvent) if this trigger already fired for the current
    ServiceDay."""
    if _already_sent_today(
        session, action=action, entity_type=entity_type, entity_id=entity_id, service_day_id=service_day_id
    ):
        return None

    recipients = _management_emails(session, venue=venue)
    message_ids = [send_email(to=email, subject=subject, body=body).message_id for email in recipients]

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, service_day_id=service_day_id,
    ) as audit:
        audit.record(
            action=action, entity_type=entity_type, entity_id=entity_id,
            after={"recipients": recipients, "message_ids": message_ids, "subject": subject},
        )
    return SentNotification(
        action=action, entity_type=entity_type, entity_id=entity_id, recipients=recipients, subject=subject,
    )


def _check_approaching_cutoffs(
    session: Session, *, venue: Venue, service_day_id: uuid.UUID, as_of: datetime,
) -> list[SentNotification]:
    sent: list[SentNotification] = []
    for cutoff in compute_approaching_cutoffs(session, venue=venue, as_of=as_of):
        subject = f"Order cut-off approaching — {cutoff.supplier_name}"
        body = (
            f"The order cut-off for your draft order with {cutoff.supplier_name} "
            f"is at {cutoff.cutoff_at.isoformat()}."
        )
        result = _notify_management(
            session, venue=venue, service_day_id=service_day_id,
            action=ORDER_CUTOFF_ACTION, entity_type="purchase_order", entity_id=cutoff.purchase_order_id,
            subject=subject, body=body,
        )
        if result is not None:
            sent.append(result)
    return sent


def _check_unfilled_shifts(
    session: Session, *, venue: Venue, service_day_id: uuid.UUID, as_of: datetime,
) -> list[SentNotification]:
    """Scans every business_date the next UNFILLED_SHIFT_WINDOW could touch
    (today, tomorrow, the day after — safely covers 48h regardless of where
    as_of falls in the venue's own day boundary), then keeps only the
    warnings whose window actually starts within that horizon — a coverage
    gap for a window later this week isn't "within 48h" yet. Each
    coverage_rule_id notifies at most once per call even if it's short on
    more than one of those business dates, matching the dedup's own
    per-ServiceDay-of-the-check granularity."""
    sent: list[SentNotification] = []
    seen_rule_ids: set[uuid.UUID] = set()
    horizon_end = as_of + UNFILLED_SHIFT_WINDOW
    tz = ZoneInfo(venue.timezone)

    candidate_dates = sorted({resolve_business_date(venue, as_of + timedelta(hours=h)) for h in (0, 24, 48)})
    for business_date in candidate_dates:
        for warning in compute_coverage_warnings(session, venue=venue, business_date=business_date):
            if warning.coverage_rule_id in seen_rule_ids:
                continue
            window_start_at = datetime.combine(business_date, warning.window_start, tzinfo=tz)
            if not (as_of <= window_start_at <= horizon_end):
                continue
            seen_rule_ids.add(warning.coverage_rule_id)

            subject = "Unfilled shift within 48 hours"
            body = (
                f"A station needs {warning.minimum_staff} staff "
                f"({warning.scheduled_staff} currently scheduled) for the coverage window "
                f"starting {window_start_at.isoformat()}."
            )
            result = _notify_management(
                session, venue=venue, service_day_id=service_day_id,
                action=UNFILLED_SHIFT_ACTION, entity_type="station_coverage_rule",
                entity_id=warning.coverage_rule_id, subject=subject, body=body,
            )
            if result is not None:
                sent.append(result)
    return sent


def _check_stale_equipment_issues(
    session: Session, *, venue: Venue, service_day_id: uuid.UUID, as_of: datetime,
) -> list[SentNotification]:
    sent: list[SentNotification] = []
    for issue in get_open_equipment_issues(session, venue=venue):
        if as_of - issue.opened_at < STALE_EQUIPMENT_ISSUE_THRESHOLD:
            continue
        equipment_item = session.get(EquipmentItem, issue.equipment_item_id)
        subject = f"Equipment issue open over 24 hours — {equipment_item.name}"
        body = f"{equipment_item.name} has had an open issue since {issue.opened_at.isoformat()}."
        result = _notify_management(
            session, venue=venue, service_day_id=service_day_id,
            action=STALE_EQUIPMENT_ACTION, entity_type="equipment_issue", entity_id=issue.id,
            subject=subject, body=body,
        )
        if result is not None:
            sent.append(result)
    return sent


def run_notification_checks(
    session: Session, *, venue: Venue, as_of: datetime | None = None,
) -> list[SentNotification]:
    """The single entry point a scheduler would call per venue, on some
    interval (e.g. every 15-30 minutes) in production. No scheduler exists
    in this backend build — see the HTTP route that exposes this instead."""
    as_of = as_of or datetime.now(timezone.utc)
    business_date = resolve_business_date(venue, as_of)
    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    session.commit()

    return [
        *_check_approaching_cutoffs(session, venue=venue, service_day_id=service_day.id, as_of=as_of),
        *_check_unfilled_shifts(session, venue=venue, service_day_id=service_day.id, as_of=as_of),
        *_check_stale_equipment_issues(session, venue=venue, service_day_id=service_day.id, as_of=as_of),
    ]
