"""
Epic 8 — Chef Brief. A single read-only aggregation over Epics 2-7's own
tables — this module introduces no new persisted state of its own except
the `brief.opened` AuditEvent; everything else here is a query against data
another epic already owns and writes.

This is a BACKEND build. Several locked ACs are purely front-end concerns
and are explicitly out of scope here (documented in README's Epic 8
section): the 390px "above the fold" layout, pairing color with an icon on
each tile, and "every tile links into its underlying module" (a link is a
UI affordance — what this module guarantees instead is that every section
below carries the ids a front end needs to build that link, e.g.
RosteredStaffStatus.shift_id, ApproachingCutoff.purchase_order_id).

"Brief-opened events logged per ServiceDay per user" (for weekly-active-use
/ brief-open-rate metrics) is implemented as one AuditEvent per call, with
no dedup — the metric is computed later from distinct
(service_day_id, actor_user_id, recorded_at) rows, so an unconditional log
here is correct, not a bug to fix; the alternative (silently swallowing a
second open the same day) would make "weekly-active-use" undercount.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.equipment import EquipmentIssue
from app.models.handover import Handover
from app.models.menu import MenuAvailabilityEvent, MenuAvailabilityStatus, MenuItem
from app.models.prep import PrepTask, PrepTaskStatus
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.models.roster import Shift, ShiftStatus
from app.models.service_day import ServiceDay
from app.models.staff import Staff
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.attendance_service import get_current_status
from app.services.audit_service import audited_transaction
from app.services.handover_service import get_handover_for_service_day, get_open_equipment_issues
from app.services.roster_service import CoverageWarning, compute_coverage_warnings
from app.services.service_day_service import get_or_create_service_day, resolve_business_date

# Order approaching a cut-off within this many hours surfaces on the Brief.
# Not locked-spec-specified beyond "approaching" — chosen to match a chef
# checking the Brief once at the start of a shift and still having time to
# act before the supplier's cut-off closes.
APPROACHING_CUTOFF_WINDOW = timedelta(hours=24)

_WEEKDAY_ABBREVIATIONS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class RosteredStaffStatus:
    shift_id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    station_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    # None = "expected" — no AttendanceEvent logged yet (attendance_service's
    # own derived-read convention, reused verbatim here).
    attendance_status: str | None


@dataclass
class MenuItemAvailabilityStatus:
    menu_item_id: uuid.UUID
    menu_item_name: str
    status: MenuAvailabilityStatus
    quantity_remaining: Decimal | None
    recorded_at: datetime


@dataclass
class ApproachingCutoff:
    supplier_id: uuid.UUID
    supplier_name: str
    purchase_order_id: uuid.UUID
    cutoff_at: datetime


@dataclass
class ChefBrief:
    service_day_id: uuid.UUID
    business_date: date
    rostered_staff: list[RosteredStaffStatus] = field(default_factory=list)
    coverage_gaps: list[CoverageWarning] = field(default_factory=list)
    priority_open_prep_tasks: list[PrepTask] = field(default_factory=list)
    approaching_order_cutoffs: list[ApproachingCutoff] = field(default_factory=list)
    open_equipment_issues: list[EquipmentIssue] = field(default_factory=list)
    yesterdays_handover: Handover | None = None
    carried_forward_tasks: list[PrepTask] = field(default_factory=list)
    unavailable_or_low_menu_items: list[MenuItemAvailabilityStatus] = field(default_factory=list)


def _rostered_staff(session: Session, *, service_day: ServiceDay) -> list[RosteredStaffStatus]:
    """"Rostered" = scheduled, same definition compute_coverage_warnings
    already uses (draft OR published, not cancelled) — a chef opening the
    Brief before publishing should still see who's meant to be on, not only
    the confirmed subset."""
    rows = (
        session.query(Shift, Staff.name)
        .join(Staff, Shift.staff_id == Staff.id)
        .filter(Shift.service_day_id == service_day.id, Shift.status != ShiftStatus.cancelled)
        .order_by(Shift.start_at)
        .all()
    )
    return [
        RosteredStaffStatus(
            shift_id=shift.id, staff_id=shift.staff_id, staff_name=staff_name,
            station_id=shift.station_id, start_at=shift.start_at, end_at=shift.end_at,
            attendance_status=(status.value if (status := get_current_status(session, shift=shift)) else None),
        )
        for shift, staff_name in rows
    ]


def _priority_open_prep_tasks(session: Session, *, service_day: ServiceDay) -> list[PrepTask]:
    return (
        session.query(PrepTask)
        .filter(PrepTask.service_day_id == service_day.id, PrepTask.status != PrepTaskStatus.done)
        .order_by(PrepTask.priority.desc(), PrepTask.created_at)
        .all()
    )


def _carried_forward_tasks(session: Session, *, service_day: ServiceDay) -> list[PrepTask]:
    return (
        session.query(PrepTask)
        .filter(PrepTask.service_day_id == service_day.id, PrepTask.carried_from_task_id.isnot(None))
        .order_by(PrepTask.created_at)
        .all()
    )


def _unavailable_or_low_menu_items(session: Session, *, service_day: ServiceDay) -> list[MenuItemAvailabilityStatus]:
    """MenuAvailabilityEvent is a log (see its own docstring) — "current"
    status per MenuItem is the latest event by recorded_at, never a stored
    column. Walking events oldest-first and overwriting a dict by
    menu_item_id is the simplest correct way to collapse "all of today's
    events" down to "current status per item" without a window-function
    query, and mirrors attendance_service.get_current_status's own
    latest-wins rule."""
    rows = (
        session.query(MenuAvailabilityEvent, MenuItem.name)
        .join(MenuItem, MenuAvailabilityEvent.menu_item_id == MenuItem.id)
        .filter(MenuAvailabilityEvent.service_day_id == service_day.id)
        .order_by(MenuAvailabilityEvent.recorded_at)
        .all()
    )
    latest_by_item: dict[uuid.UUID, MenuItemAvailabilityStatus] = {}
    for event, menu_item_name in rows:
        latest_by_item[event.menu_item_id] = MenuItemAvailabilityStatus(
            menu_item_id=event.menu_item_id, menu_item_name=menu_item_name, status=event.status,
            quantity_remaining=event.quantity_remaining, recorded_at=event.recorded_at,
        )
    return [
        item for item in latest_by_item.values() if item.status != MenuAvailabilityStatus.available
    ]


def _next_cutoff_at(supplier: Supplier, venue: Venue, as_of: datetime) -> datetime | None:
    """The next datetime (in the venue's own timezone) a Supplier with
    order_days ("mon,thu" — see Supplier.order_days's own docstring) and a
    cutoff_time next closes for orders, on or after `as_of`. None if the
    supplier hasn't configured both fields — "approaching" isn't computable
    without them, so such suppliers are silently excluded rather than
    guessed at."""
    if not supplier.order_days or supplier.cutoff_time is None:
        return None
    order_weekdays = {
        _WEEKDAY_ABBREVIATIONS.index(day)
        for raw in supplier.order_days.split(",")
        if (day := raw.strip().lower()) in _WEEKDAY_ABBREVIATIONS
    }
    if not order_weekdays:
        return None

    tz = ZoneInfo(venue.timezone)
    local_as_of = as_of.astimezone(tz)
    for days_ahead in range(8):  # today .. one full week out always finds a hit
        candidate_date = local_as_of.date() + timedelta(days=days_ahead)
        if candidate_date.weekday() not in order_weekdays:
            continue
        candidate_at = datetime.combine(candidate_date, supplier.cutoff_time, tzinfo=tz)
        if candidate_at >= local_as_of:
            return candidate_at
    return None  # pragma: no cover — unreachable, order_weekdays is non-empty


def compute_approaching_cutoffs(
    session: Session, *, venue: Venue, as_of: datetime | None = None
) -> list[ApproachingCutoff]:
    """Public (like roster_service.compute_coverage_warnings) so it's
    directly, deterministically testable via an explicit as_of rather than
    only through get_chef_brief's real-wall-clock default.

    Only drafts with at least one line — an empty draft is nothing a
    supplier is waiting on (same "can't send with no lines" reasoning as
    supplier_order_service.send_purchase_order)."""
    as_of = as_of or datetime.now(timezone.utc)
    draft_orders = (
        session.query(PurchaseOrder)
        .filter(PurchaseOrder.venue_id == venue.id, PurchaseOrder.status == PurchaseOrderStatus.draft)
        .all()
    )
    supplier_cache: dict[uuid.UUID, Supplier] = {}
    approaching: list[ApproachingCutoff] = []
    for order in draft_orders:
        if not order.lines:
            continue
        supplier = supplier_cache.get(order.supplier_id)
        if supplier is None:
            supplier = session.get(Supplier, order.supplier_id)
            supplier_cache[order.supplier_id] = supplier
        cutoff_at = _next_cutoff_at(supplier, venue, as_of)
        if cutoff_at is not None and cutoff_at - as_of <= APPROACHING_CUTOFF_WINDOW:
            approaching.append(
                ApproachingCutoff(
                    supplier_id=supplier.id, supplier_name=supplier.name,
                    purchase_order_id=order.id, cutoff_at=cutoff_at,
                )
            )
    return sorted(approaching, key=lambda item: item.cutoff_at)


def _yesterdays_handover(session: Session, *, venue: Venue, business_date: date) -> Handover | None:
    yesterday = business_date - timedelta(days=1)
    yesterdays_service_day = (
        session.query(ServiceDay).filter_by(venue_id=venue.id, business_date=yesterday).one_or_none()
    )
    if yesterdays_service_day is None:
        return None
    return get_handover_for_service_day(session, service_day_id=yesterdays_service_day.id)


def get_chef_brief(
    session: Session, *, venue: Venue, actor: User, business_date: date | None = None
) -> ChefBrief:
    """Default landing view = current ServiceDay's Brief (locked AC) — pass
    an explicit business_date only to look at a different day (e.g. to
    review yesterday's after the fact); the current ServiceDay is lazily
    created on first reference here, same as every other epic's first
    operational touch of a day."""
    resolved_date = business_date or resolve_business_date(venue)
    service_day = get_or_create_service_day(session, venue=venue, business_date=resolved_date)
    session.commit()

    brief = ChefBrief(
        service_day_id=service_day.id,
        business_date=service_day.business_date,
        rostered_staff=_rostered_staff(session, service_day=service_day),
        coverage_gaps=compute_coverage_warnings(session, venue=venue, business_date=resolved_date),
        priority_open_prep_tasks=_priority_open_prep_tasks(session, service_day=service_day),
        approaching_order_cutoffs=compute_approaching_cutoffs(session, venue=venue),
        open_equipment_issues=get_open_equipment_issues(session, venue=venue),
        yesterdays_handover=_yesterdays_handover(session, venue=venue, business_date=resolved_date),
        carried_forward_tasks=_carried_forward_tasks(session, service_day=service_day),
        unavailable_or_low_menu_items=_unavailable_or_low_menu_items(session, service_day=service_day),
    )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        audit.record(
            action="brief.opened", entity_type="service_day", entity_id=service_day.id,
            after={"business_date": resolved_date.isoformat()},
        )
    return brief
