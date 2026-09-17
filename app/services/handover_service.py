"""
Epic 7 — Handover. "Close day" and "reopen day" are the two ends of the
only sanctioned way a closed ServiceDay's records can change (see
app/models/handover.py's docstring and app/services/service_day_service.py
::ServiceDayIsClosed, which prep_service/capture_service both enforce).

close_service_day is get-or-create on the Handover row (unique per
ServiceDay): the normal case creates a fresh one; closing again after a
reopen updates the SAME row (new note/timestamps, freshly repopulated
items) rather than accumulating a second Handover for one day.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.capture import Capture, CaptureType
from app.models.equipment import EquipmentIssue, EquipmentIssueStatus, EquipmentItem
from app.models.handover import Handover, HandoverItem
from app.models.menu import MenuAvailabilityEvent
from app.models.prep import PrepTask, PrepTaskStatus
from app.models.purchase_order import DeliveryIssue, PurchaseOrder, PurchaseOrderStatus
from app.models.service_day import ServiceDay, ServiceDayStatus
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class ServiceDayNotOpen(Exception):
    """close_service_day requires the day to actually be open — closing a
    day that's still "planned" (never started) or already closed isn't a
    single, measurable "open -> save" close event (locked AC)."""


class ServiceDayNotClosed(Exception):
    """reopen_service_day requires the day to actually be closed."""


def get_open_equipment_issues(session: Session, *, venue: Venue) -> list[EquipmentIssue]:
    """Venue-wide, not day-scoped — an EquipmentIssue doesn't belong to any
    one ServiceDay. Shared by close_service_day (it's one of the six
    handover categories) and the Epic 8 Chef Brief."""
    return (
        session.query(EquipmentIssue)
        .join(EquipmentItem, EquipmentIssue.equipment_item_id == EquipmentItem.id)
        .filter(EquipmentItem.venue_id == venue.id, EquipmentIssue.status == EquipmentIssueStatus.open)
        .all()
    )


def _populate_handover_items(session: Session, *, venue: Venue, service_day: ServiceDay, handover: Handover) -> None:
    not_done_tasks = (
        session.query(PrepTask)
        .filter(PrepTask.service_day_id == service_day.id, PrepTask.status != PrepTaskStatus.done)
        .all()
    )
    for task in not_done_tasks:
        session.add(HandoverItem(handover_id=handover.id, prep_task_id=task.id))

    todays_events = session.query(MenuAvailabilityEvent).filter_by(service_day_id=service_day.id).all()
    for event in todays_events:
        session.add(HandoverItem(handover_id=handover.id, menu_availability_event_id=event.id))

    for issue in get_open_equipment_issues(session, venue=venue):
        session.add(HandoverItem(handover_id=handover.id, equipment_issue_id=issue.id))

    # "Open" DeliveryIssue: no separate status column (Epic 5) — an
    # unresolved one is simply one with no resolution recorded yet.
    open_delivery_issues = (
        session.query(DeliveryIssue)
        .join(PurchaseOrder, DeliveryIssue.purchase_order_id == PurchaseOrder.id)
        .filter(PurchaseOrder.venue_id == venue.id, DeliveryIssue.resolution.is_(None))
        .all()
    )
    for issue in open_delivery_issues:
        session.add(HandoverItem(handover_id=handover.id, delivery_issue_id=issue.id))

    draft_or_sent_orders = (
        session.query(PurchaseOrder)
        .filter(
            PurchaseOrder.venue_id == venue.id,
            PurchaseOrder.status.in_([PurchaseOrderStatus.draft, PurchaseOrderStatus.sent]),
        )
        .all()
    )
    for order in draft_or_sent_orders:
        session.add(HandoverItem(handover_id=handover.id, purchase_order_id=order.id))

    unparsed_captures = (
        session.query(Capture)
        .filter(Capture.service_day_id == service_day.id, Capture.capture_type == CaptureType.unparsed)
        .all()
    )
    for capture in unparsed_captures:
        session.add(HandoverItem(handover_id=handover.id, capture_id=capture.id))


def close_service_day(
    session: Session, *, venue: Venue, actor: User, service_day: ServiceDay, note: str | None = None
) -> Handover:
    if service_day.status != ServiceDayStatus.open:
        raise ServiceDayNotOpen(
            f"ServiceDay {service_day.id} is {service_day.status.value}, not open — cannot close it"
        )

    closed_at = datetime.now(timezone.utc)
    time_to_close_seconds = (
        int((closed_at - service_day.opened_at).total_seconds()) if service_day.opened_at else 0
    )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        before_status = service_day.status.value
        service_day.status = ServiceDayStatus.closed
        service_day.closed_at = closed_at
        session.add(service_day)

        existing = session.query(Handover).filter_by(service_day_id=service_day.id).one_or_none()
        if existing is not None:
            # Re-closing after a reopen — same Handover row, fresh items.
            for item in list(existing.items):
                session.delete(item)
            handover = existing
            handover.note = note
            handover.closed_by = actor.id
            handover.closed_at = closed_at
            handover.time_to_close_seconds = time_to_close_seconds
        else:
            handover = Handover(
                venue_id=venue.id, service_day_id=service_day.id, note=note,
                closed_by=actor.id, closed_at=closed_at, time_to_close_seconds=time_to_close_seconds,
            )
            session.add(handover)
        session.flush()

        _populate_handover_items(session, venue=venue, service_day=service_day, handover=handover)
        session.flush()

        audit.record(
            action="service_day.closed", entity_type="service_day", entity_id=service_day.id,
            before={"status": before_status}, after={"status": "closed"},
        )
        audit.record(
            action="handover.saved", entity_type="handover", entity_id=handover.id,
            after={
                "note": note, "item_count": len(handover.items),
                "time_to_close_seconds": time_to_close_seconds,
                # Epic 11 metrics wiring: "logged with open/close
                # timestamps" — opened_at/closed_at inline on the event
                # itself, not just derivable by joining back to ServiceDay.
                "opened_at": service_day.opened_at.isoformat() if service_day.opened_at else None,
                "closed_at": closed_at.isoformat(),
            },
        )
    return handover


def reopen_service_day(session: Session, *, venue: Venue, actor: User, service_day: ServiceDay, reason: str) -> ServiceDay:
    """Explicit, audited "who, when, why" — the AuditEvent's actor_user_id
    and recorded_at give who/when for free; reason carries the why. No
    guardrail on WHO may call this beyond the route's own role check —
    the audit trail is the accountability mechanism the locked AC asks for,
    not a second permission tier."""
    if service_day.status != ServiceDayStatus.closed:
        raise ServiceDayNotClosed(f"ServiceDay {service_day.id} is {service_day.status.value}, not closed")

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        service_day.status = ServiceDayStatus.open
        session.add(service_day)
        session.flush()
        audit.record(
            action="service_day.reopened", entity_type="service_day", entity_id=service_day.id,
            before={"status": "closed"}, after={"status": "open", "reason": reason},
        )
    return service_day


def set_handover_item_included(
    session: Session, *, venue: Venue, actor: User, handover_item: HandoverItem, included: bool
) -> HandoverItem:
    """Toggling included never touches the referenced record — it only
    changes whether this item shows up on the handover view (locked AC)."""
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
    ) as audit:
        before = handover_item.included
        handover_item.included = included
        session.add(handover_item)
        session.flush()
        audit.record(
            action="handover_item.included_toggled", entity_type="handover_item", entity_id=handover_item.id,
            before={"included": before}, after={"included": included},
        )
    return handover_item


def get_handover_for_service_day(session: Session, *, service_day_id: uuid.UUID) -> Handover | None:
    return session.query(Handover).filter_by(service_day_id=service_day_id).one_or_none()
