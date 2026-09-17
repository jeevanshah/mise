"""
Epic 2 — Kitchen Roster (service layer).

Covers every AC in the locked spec's Epic 2:
  - Shift create with cross-station overlap prevention for a Staff member.
  - "Copy last week" duplicating Shifts into a new week, creating
    ServiceDays as needed.
  - Shift.status / StaffResponse.status as independent state machines.
  - "Publish roster" (draft -> published) queuing a notification per
    affected Staff — Epic 10 (email) doesn't exist yet, so this stubs the
    queue as an AuditEvent and surfaces the signed-link dev token directly,
    exactly like auth_service's dev_token pattern for magic links.
  - Coverage warnings against StationCoverageRule.
  - Staff responding via login or a signed StaffLink (confirm/decline).

Every mutation goes through audited_transaction; multi-row creates (Shift +
its StaffResponse, or a lazily-created ServiceDay) follow the same
flush-then-audited-transaction pattern as onboarding_service and
staffing_service — see onboarding_service.create_organisation_with_venue's
docstring for why.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.roster import Shift, ShiftStatus, StaffLink, StaffResponse, StaffResponseStatus
from app.models.service_day import ServiceDay
from app.models.staff import Staff
from app.models.station import Station, StationCoverageRule
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.email_service import send_email
from app.services.service_day_service import get_or_create_service_day, resolve_business_date

# How long a signed staff link is valid for once issued at publish time —
# long enough to cover a roster published up to two weeks ahead of service.
STAFF_LINK_EXPIRE_DAYS = 14


class InvalidShiftWindow(Exception):
    """start_at/end_at must be timezone-aware, and start_at must be before
    end_at."""


class OverlappingShift(Exception):
    """A Staff member cannot be saved into two Shifts with overlapping
    times, including across different Stations — checked before saving,
    not discovered after (locked AC)."""


class CannotPublishCancelledShift(Exception):
    pass


class ShiftNotRespondable(Exception):
    """A cancelled Shift can't be confirmed/declined."""


class InvalidStaffLink(Exception):
    """Unknown token, revoked, expired, or the underlying Shift is
    cancelled — deliberately one exception for all of these, same reasoning
    as auth_service.InvalidOrExpiredToken: never let a caller distinguish
    which failure mode a guessed/stale token hit."""


class CopyWeekConflict(Exception):
    """Copying would create an overlapping Shift for some Staff member —
    either against a Shift already in the target week, or against another
    Shift in the same copy batch. Nothing from the copy is created; the
    whole operation is validated before anything is written."""


def _resolve_staff_email(session: Session, *, staff: Staff) -> str | None:
    """Epic 10 — the one email address a Staff member can be reached at for
    roster notifications. A Staff WITH a login (user_id set) is reached at
    their User.email — their actual identity, always present and unique.
    A Staff with no login at all falls back to their own contact_email
    (set at creation for exactly this reason — see Staff's own docstring).
    Neither present resolves to None: the caller records that no delivery
    address was on file rather than guessing or failing."""
    if staff.user_id is not None:
        user = session.get(User, staff.user_id)
        if user is not None and user.email:
            return user.email
    return staff.contact_email


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


def _overlap_exists(
    session: Session, *, staff_id: uuid.UUID, start_at: datetime, end_at: datetime
) -> bool:
    return session.query(
        session.query(Shift)
        .filter(
            Shift.staff_id == staff_id,
            Shift.status != ShiftStatus.cancelled,
            Shift.start_at < end_at,
            Shift.end_at > start_at,
        )
        .exists()
    ).scalar()


# --- Create / cancel ---------------------------------------------------


def create_shift(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    station: Station,
    staff: Staff,
    start_at: datetime,
    end_at: datetime,
) -> Shift:
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise InvalidShiftWindow("start_at/end_at must be timezone-aware")
    if start_at >= end_at:
        raise InvalidShiftWindow("start_at must be before end_at")
    if _overlap_exists(session, staff_id=staff.id, start_at=start_at, end_at=end_at):
        raise OverlappingShift(
            f"{staff.name} already has a shift overlapping "
            f"{start_at.isoformat()}–{end_at.isoformat()}"
        )

    business_date = resolve_business_date(venue, start_at)
    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)

    shift = Shift(
        venue_id=venue.id,
        service_day_id=service_day.id,
        station_id=station.id,
        staff_id=staff.id,
        start_at=start_at,
        end_at=end_at,
        status=ShiftStatus.draft,
    )
    session.add(shift)
    session.flush()

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        response = StaffResponse(
            shift_id=shift.id, staff_id=staff.id, status=StaffResponseStatus.pending
        )
        session.add(response)
        session.flush()
        audit.record(
            action="shift.created",
            entity_type="shift",
            entity_id=shift.id,
            after={
                "station_id": str(station.id),
                "staff_id": str(staff.id),
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "status": shift.status.value,
            },
        )
    return shift


def cancel_shift(session: Session, *, venue: Venue, actor: User, shift: Shift) -> Shift:
    """Idempotent: an already-cancelled Shift is a no-op, no duplicate
    AuditEvent. Revokes any StaffLink issued for this Shift as part of the
    same transaction — a signed link is only ever valid for a live Shift.

    Epic 10 — notifies the assigned Staff member only if the Shift had
    actually been published (they were never told about a draft, so
    cancelling one is silent, same "only a real transition notifies"
    reasoning as publish_shift's own idempotency)."""
    if shift.status == ShiftStatus.cancelled:
        return shift
    was_published = shift.status == ShiftStatus.published

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id,
        service_day_id=shift.service_day_id,
    ) as audit:
        before_status = shift.status.value
        shift.status = ShiftStatus.cancelled
        session.add(shift)
        session.flush()
        audit.record(
            action="shift.cancelled",
            entity_type="shift",
            entity_id=shift.id,
            before={"status": before_status},
            after={"status": "cancelled"},
        )

        revoked = (
            session.query(StaffLink)
            .filter(StaffLink.shift_id == shift.id, StaffLink.revoked_at.is_(None))
            .update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
        )
        if revoked:
            audit.record(
                action="staff_link.revoked",
                entity_type="shift",
                entity_id=shift.id,
                after={"revoked_count": revoked},
            )

        if was_published:
            staff = session.get(Staff, shift.staff_id)
            staff_email = _resolve_staff_email(session, staff=staff)
            message_id = None
            if staff_email:
                message_id = send_email(
                    to=staff_email,
                    subject="Shift cancelled",
                    body=(
                        f"Hi {staff.name}, your shift on "
                        f"{shift.start_at.isoformat()}–{shift.end_at.isoformat()} has been cancelled."
                    ),
                ).message_id
            audit.record(
                action="roster.notification_queued",
                entity_type="staff",
                entity_id=staff.id,
                after={
                    "shift_id": str(shift.id), "channel": "email", "reason": "shift_cancelled",
                    "sent": message_id is not None, "message_id": message_id,
                },
            )

    return shift


# --- Publish -------------------------------------------------------------


@dataclass
class IssuedStaffLink:
    staff_link: StaffLink
    raw_token: str
    expires_at: datetime


def issue_staff_link(session: Session, *, staff: Staff, shift: Shift) -> IssuedStaffLink:
    raw_token = _generate_raw_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=STAFF_LINK_EXPIRE_DAYS)
    link = StaffLink(
        staff_id=staff.id,
        shift_id=shift.id,
        token_hash=_hash_token(raw_token),
        expires_at=expires_at,
    )
    session.add(link)
    session.flush()
    return IssuedStaffLink(staff_link=link, raw_token=raw_token, expires_at=expires_at)


@dataclass
class PublishResult:
    shift: Shift
    staff_link_raw_token: str | None  # None when the shift was already published (no-op)


def publish_shift(session: Session, *, venue: Venue, actor: User, shift: Shift) -> PublishResult:
    """draft -> published. Idempotent (already-published is a no-op, same
    reasoning as open_service_day — no duplicate notification for a
    republish). Issues a fresh signed StaffLink and emails the assigned
    Staff member (Epic 10 — see _resolve_staff_email) as part of the same
    transaction; the raw token is ALSO still returned to the caller
    directly, exactly like auth_service's dev_token, since there's no UI
    that reads email in this backend build and every earlier epic's own
    live verification has relied on it."""
    if shift.status == ShiftStatus.cancelled:
        raise CannotPublishCancelledShift("Cannot publish a cancelled shift")
    if shift.status == ShiftStatus.published:
        return PublishResult(shift=shift, staff_link_raw_token=None)

    staff = session.get(Staff, shift.staff_id)

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id,
        service_day_id=shift.service_day_id,
    ) as audit:
        shift.status = ShiftStatus.published
        session.add(shift)
        session.flush()
        audit.record(
            action="shift.published",
            entity_type="shift",
            entity_id=shift.id,
            before={"status": "draft"},
            after={"status": "published"},
        )

        issued = issue_staff_link(session, staff=staff, shift=shift)
        audit.record(
            action="staff_link.issued",
            entity_type="staff_link",
            entity_id=issued.staff_link.id,
            after={
                "staff_id": str(staff.id),
                "shift_id": str(shift.id),
                "expires_at": issued.expires_at.isoformat(),
            },
        )
        # Epic 10 — real email delivery, via the one shared EmailSender
        # hook. "sent" records whether a delivery address was actually on
        # file (see _resolve_staff_email) — a Staff member with neither a
        # login nor a contact_email still gets published/scheduled, just
        # with no notification, exactly like Epic 5's PurchaseOrder can
        # still be built with a supplier that has no contact_email on file.
        staff_email = _resolve_staff_email(session, staff=staff)
        message_id = None
        if staff_email:
            message_id = send_email(
                to=staff_email,
                subject="New shift published",
                body=(
                    f"Hi {staff.name}, you've been rostered on for "
                    f"{shift.start_at.isoformat()}–{shift.end_at.isoformat()}. "
                    f"Confirm or decline using this link token: {issued.raw_token}"
                ),
            ).message_id
        audit.record(
            action="roster.notification_queued",
            entity_type="staff",
            entity_id=staff.id,
            after={
                "shift_id": str(shift.id), "channel": "email", "reason": "shift_published",
                "sent": message_id is not None, "message_id": message_id,
            },
        )

    return PublishResult(shift=shift, staff_link_raw_token=issued.raw_token)


def publish_week(
    session: Session, *, venue: Venue, actor: User, week_start: date
) -> list[PublishResult]:
    """Publishes every draft Shift whose business_date falls in the 7 days
    starting week_start. Each Shift's publish is its own atomic transaction
    (see publish_shift) — this loops rather than wrapping the whole week in
    one transaction, since the AC's unit of audit is the Shift, not the
    week."""
    shifts = (
        session.query(Shift)
        .join(ServiceDay, Shift.service_day_id == ServiceDay.id)
        .filter(
            ServiceDay.venue_id == venue.id,
            ServiceDay.business_date >= week_start,
            ServiceDay.business_date < week_start + timedelta(days=7),
            Shift.status == ShiftStatus.draft,
        )
        .all()
    )
    return [publish_shift(session, venue=venue, actor=actor, shift=shift) for shift in shifts]


# --- Copy last week ------------------------------------------------------


def copy_week(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    source_week_start: date,
    target_week_start: date,
) -> list[Shift]:
    """Duplicates every non-cancelled Shift whose business_date falls in
    the 7 days starting source_week_start into the 7 days starting
    target_week_start, creating target ServiceDays as needed. New Shifts
    are always draft — a copy is a starting point, not an already-published
    roster. Local wall-clock time-of-day is preserved (not the raw UTC
    offset), so a 6pm start stays 6pm even across a DST transition between
    the two weeks; the venue's own timezone does that conversion.

    Validated in two passes: every prospective new Shift is checked for
    overlap (against existing Shifts and against each other) BEFORE
    anything is written, so a conflict aborts the whole copy with nothing
    created rather than leaving a partial week behind.
    """
    if target_week_start == source_week_start:
        raise ValueError("target_week_start must differ from source_week_start")

    tz = ZoneInfo(venue.timezone)
    delta_days = (target_week_start - source_week_start).days

    source_shifts = (
        session.query(Shift)
        .join(ServiceDay, Shift.service_day_id == ServiceDay.id)
        .filter(
            ServiceDay.venue_id == venue.id,
            ServiceDay.business_date >= source_week_start,
            ServiceDay.business_date < source_week_start + timedelta(days=7),
            Shift.status != ShiftStatus.cancelled,
        )
        .all()
    )
    if not source_shifts:
        return []

    planned: list[tuple[Shift, datetime, datetime]] = []
    for shift in source_shifts:
        local_start = shift.start_at.astimezone(tz)
        local_end = shift.end_at.astimezone(tz)
        new_start_at = datetime.combine(
            local_start.date() + timedelta(days=delta_days), local_start.time(), tzinfo=tz
        ).astimezone(timezone.utc)
        new_end_at = datetime.combine(
            local_end.date() + timedelta(days=delta_days), local_end.time(), tzinfo=tz
        ).astimezone(timezone.utc)
        planned.append((shift, new_start_at, new_end_at))

    for i, (shift, new_start_at, new_end_at) in enumerate(planned):
        if _overlap_exists(session, staff_id=shift.staff_id, start_at=new_start_at, end_at=new_end_at):
            raise CopyWeekConflict(
                f"Copying shift {shift.id} would overlap an existing shift for staff {shift.staff_id}"
            )
        for j, (other_shift, other_start_at, other_end_at) in enumerate(planned):
            if (
                i != j
                and other_shift.staff_id == shift.staff_id
                and new_start_at < other_end_at
                and new_end_at > other_start_at
            ):
                raise CopyWeekConflict(
                    f"Copying shifts {shift.id} and {other_shift.id} would overlap "
                    f"for staff {shift.staff_id}"
                )

    created: list[Shift] = []
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        for shift, new_start_at, new_end_at in planned:
            business_date = resolve_business_date(venue, new_start_at)
            service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)

            new_shift = Shift(
                venue_id=venue.id,
                service_day_id=service_day.id,
                station_id=shift.station_id,
                staff_id=shift.staff_id,
                start_at=new_start_at,
                end_at=new_end_at,
                status=ShiftStatus.draft,
            )
            session.add(new_shift)
            session.flush()

            response = StaffResponse(
                shift_id=new_shift.id, staff_id=shift.staff_id, status=StaffResponseStatus.pending
            )
            session.add(response)
            session.flush()

            audit.record(
                action="shift.created",
                entity_type="shift",
                entity_id=new_shift.id,
                after={
                    "station_id": str(shift.station_id),
                    "staff_id": str(shift.staff_id),
                    "start_at": new_start_at.isoformat(),
                    "end_at": new_end_at.isoformat(),
                    "status": "draft",
                    "copied_from_shift_id": str(shift.id),
                },
                service_day_id=service_day.id,
            )
            created.append(new_shift)

    return created


# --- Staff responses -------------------------------------------------------


def _apply_response(
    session: Session,
    *,
    venue: Venue,
    shift: Shift,
    response_status: StaffResponseStatus,
    via: str,
    actor: User | None,
) -> StaffResponse:
    if shift.status == ShiftStatus.cancelled:
        raise ShiftNotRespondable("This shift has been cancelled")

    response = session.query(StaffResponse).filter_by(shift_id=shift.id).one()

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id if actor else None,
        service_day_id=shift.service_day_id,
    ) as audit:
        before_status = response.status.value
        response.status = response_status
        response.responded_at = datetime.now(timezone.utc)
        response.responded_via = via
        session.add(response)
        session.flush()
        audit.record(
            action="staff_response.updated",
            entity_type="staff_response",
            entity_id=response.id,
            before={"status": before_status},
            after={"status": response_status.value, "via": via},
        )

    return response


def respond_to_shift_as_staff(
    session: Session,
    *,
    venue: Venue,
    shift: Shift,
    actor: User,
    response_status: StaffResponseStatus,
) -> StaffResponse:
    """The "via login" path — the route layer is responsible for having
    already verified that `actor`'s own Staff record is the one assigned to
    this Shift."""
    return _apply_response(
        session, venue=venue, shift=shift, response_status=response_status, via="login", actor=actor
    )


def resolve_staff_link(session: Session, *, raw_token: str) -> tuple[Shift, Staff]:
    """Validates a raw signed-link token end to end — exists, not revoked,
    not expired, and its Shift still exists and isn't cancelled — and
    returns the Shift + Staff it grants access to. Used by both the
    "view my shift" and "respond" endpoints so a caller never sees which
    specific check failed (InvalidStaffLink's docstring)."""
    link = session.query(StaffLink).filter_by(token_hash=_hash_token(raw_token)).one_or_none()
    if link is None or link.revoked_at is not None or link.expires_at < datetime.now(timezone.utc):
        raise InvalidStaffLink("This link is invalid or has expired")

    shift = session.get(Shift, link.shift_id)
    if shift is None or shift.status == ShiftStatus.cancelled:
        raise InvalidStaffLink("This link is invalid or has expired")

    staff = session.get(Staff, link.staff_id)
    if staff is None:  # pragma: no cover — FK guarantees this in practice
        raise InvalidStaffLink("This link is invalid or has expired")

    return shift, staff


def respond_to_shift_via_link(
    session: Session, *, raw_token: str, response_status: StaffResponseStatus
) -> StaffResponse:
    """The "via signed link" path — no login required. Resolves the Venue
    from the Shift itself, since a public, token-authenticated endpoint has
    no venue_id in its URL to begin with."""
    shift, _staff = resolve_staff_link(session, raw_token=raw_token)
    venue = session.get(Venue, shift.venue_id)
    return _apply_response(
        session, venue=venue, shift=shift, response_status=response_status, via="staff_link", actor=None
    )


# --- Coverage warnings -----------------------------------------------------


@dataclass
class CoverageWarning:
    station_id: uuid.UUID
    coverage_rule_id: uuid.UUID
    day_of_week: int
    window_start: time
    window_end: time
    minimum_staff: int
    scheduled_staff: int


def compute_coverage_warnings(
    session: Session, *, venue: Venue, business_date: date
) -> list[CoverageWarning]:
    """A warning fires when scheduled Shifts for a Station overlapping a
    StationCoverageRule's day/time window fall below that rule's
    minimum_staff — a single short shift outside the window doesn't count
    (locked AC). "Scheduled" here means draft OR published (not cancelled)
    — a chef building next week's roster should see gaps immediately, not
    only after publishing. A rule's window is always same-calendar-day
    (window_start < window_end enforced at creation), so it maps onto
    business_date the same unambiguous way a Shift's own business_date is
    anchored to when it starts."""
    tz = ZoneInfo(venue.timezone)
    day_of_week = business_date.weekday()

    rules = (
        session.query(StationCoverageRule)
        .filter_by(venue_id=venue.id, day_of_week=day_of_week)
        .all()
    )
    if not rules:
        return []

    service_day = (
        session.query(ServiceDay)
        .filter_by(venue_id=venue.id, business_date=business_date)
        .one_or_none()
    )
    shifts = []
    if service_day is not None:
        shifts = (
            session.query(Shift)
            .filter(Shift.service_day_id == service_day.id, Shift.status != ShiftStatus.cancelled)
            .all()
        )

    warnings: list[CoverageWarning] = []
    for rule in rules:
        window_start_at = datetime.combine(business_date, rule.window_start, tzinfo=tz)
        window_end_at = datetime.combine(business_date, rule.window_end, tzinfo=tz)
        covering_staff = {
            shift.staff_id
            for shift in shifts
            if shift.station_id == rule.station_id
            and shift.start_at < window_end_at
            and shift.end_at > window_start_at
        }
        if len(covering_staff) < rule.minimum_staff:
            warnings.append(
                CoverageWarning(
                    station_id=rule.station_id,
                    coverage_rule_id=rule.id,
                    day_of_week=rule.day_of_week,
                    window_start=rule.window_start,
                    window_end=rule.window_end,
                    minimum_staff=rule.minimum_staff,
                    scheduled_staff=len(covering_staff),
                )
            )
    return warnings
