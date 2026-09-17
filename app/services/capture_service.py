"""
Epic 6 — Quick Capture: the create/confirm/reject lifecycle around a
Capture row. See app/models/capture.py's docstring for what each field
means and app/services/capture_classifier.py for how a Capture is
proposed. This module is only what happens AFTER that: a chef reviews a
proposal and either confirms it (dispatching to the right downstream
action) or rejects it — both are logged on the Capture row itself
(status/decided_by/decided_at) and as a general AuditEvent, satisfying the
locked AC's "who, when, what was proposed, what was decided".

Confirming never implements its own domain logic: an eighty_six confirms
into an existing MenuAvailabilityEvent create, a restock confirms by
calling Epic 5's add_or_merge_line directly, and an equipment_issue
confirms into an EquipmentIssue create — this module is the dispatcher,
not a second copy of any of those.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.capture import Capture, CaptureStatus, CaptureType, MatchedEntityType
from app.models.equipment import EquipmentIssue, EquipmentIssuePriority, EquipmentItem
from app.models.ingredient import Ingredient
from app.models.menu import MenuAvailabilityEvent, MenuAvailabilityStatus, MenuItem
from app.models.service_day import ServiceDay, ServiceDayStatus
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.capture_classifier import ENTITY_TYPE_TO_CAPTURE_TYPE, classify_capture
from app.services.service_day_service import ServiceDayIsClosed, get_or_create_service_day, resolve_business_date
from app.services.supplier_order_service import (
    MissingOrderIdentity,
    UnknownIngredient,
    UnknownSupplier,
    add_or_merge_line,
)


class CaptureAlreadyDecided(Exception):
    """A Capture can only be confirmed or rejected once, from status=proposed."""


class UnresolvedCapture(Exception):
    """confirm_capture was called with no confident classifier match and no
    explicit entity_type/entity_id override — the AC requires an explicit
    chef choice here, never a silent best-guess."""


class UnknownMatchedEntity(Exception):
    """The resolved entity_id doesn't reference a row of entity_type at
    this venue — whether that came from the classifier or a chef override,
    it's still validated before anything downstream is created."""


class MissingConfirmationDetails(Exception):
    """The action being confirmed needs details a Capture's raw text can't
    supply on its own (e.g. a restock needs a supplier + delivery date/
    cycle to identify which draft PurchaseOrder to add the line to)."""


def create_capture(
    session: Session, *, venue: Venue, actor: User, raw_text: str,
    business_date: date | None = None, added_after_close: bool = False,
) -> Capture:
    """business_date defaults to "today" (the normal case). Pass an
    explicit (past, closed) business_date + added_after_close=True for the
    Epic 7 sanctioned late-entry path — otherwise a Capture against a
    closed ServiceDay is rejected (ServiceDayIsClosed)."""
    resolved_date = business_date or resolve_business_date(venue, datetime.now(timezone.utc))
    service_day = get_or_create_service_day(session, venue=venue, business_date=resolved_date)

    if service_day.status == ServiceDayStatus.closed and not added_after_close:
        raise ServiceDayIsClosed(
            f"ServiceDay {service_day.id} is closed — pass added_after_close=True for a sanctioned late entry"
        )
    effective_added_after_close = added_after_close and service_day.status == ServiceDayStatus.closed

    result = classify_capture(session, venue=venue, raw_text=raw_text)

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=service_day.id,
    ) as audit:
        capture = Capture(
            venue_id=venue.id,
            service_day_id=service_day.id,
            raw_text=raw_text,
            capture_type=result.capture_type,
            matched_entity_type=result.matched_entity_type,
            matched_entity_id=result.matched_entity_id,
            extracted_quantity=result.extracted_quantity,
            extracted_unit=result.extracted_unit,
            confidence=result.confidence,
            candidate_matches=result.candidate_matches or None,
            status=CaptureStatus.proposed,
            added_after_close=effective_added_after_close,
        )
        session.add(capture)
        session.flush()
        audit.record(
            action="capture.proposed", entity_type="capture", entity_id=capture.id,
            after={
                "raw_text": raw_text, "capture_type": result.capture_type.value,
                "matched_entity_type": result.matched_entity_type.value if result.matched_entity_type else None,
                "matched_entity_id": str(result.matched_entity_id) if result.matched_entity_id else None,
                "extracted_quantity": str(result.extracted_quantity) if result.extracted_quantity else None,
                "candidate_count": len(result.candidate_matches),
                "added_after_close": effective_added_after_close,
            },
        )
    return capture


def _validate_matched_entity(
    session: Session, *, venue: Venue, entity_type: MatchedEntityType, entity_id: uuid.UUID
) -> None:
    model = {
        MatchedEntityType.ingredient: Ingredient,
        MatchedEntityType.menu_item: MenuItem,
        MatchedEntityType.equipment_item: EquipmentItem,
    }[entity_type]
    if session.query(model).filter_by(id=entity_id, venue_id=venue.id).one_or_none() is None:
        raise UnknownMatchedEntity(
            f"{entity_type.value} {entity_id} does not exist at this venue"
        )


def _raise_if_service_day_closed(session: Session, service_day_id: uuid.UUID) -> None:
    """Deciding on an existing Capture (confirm/reject) is an edit, not a
    new addition — Epic 7's "read-only" applies unconditionally here, same
    as prep_service.update_prep_task_status. No added_after_close override
    exists for this path; reopen the day first."""
    service_day = session.get(ServiceDay, service_day_id)
    if service_day is not None and service_day.status == ServiceDayStatus.closed:
        raise ServiceDayIsClosed(
            f"ServiceDay {service_day.id} is closed — reopen it before deciding on an existing Capture"
        )


def reject_capture(session: Session, *, venue: Venue, actor: User, capture: Capture, reason: str | None = None) -> Capture:
    if capture.status != CaptureStatus.proposed:
        raise CaptureAlreadyDecided(f"Capture {capture.id} is already {capture.status.value}")
    _raise_if_service_day_closed(session, capture.service_day_id)

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=capture.service_day_id,
    ) as audit:
        capture.status = CaptureStatus.rejected
        capture.decided_by = actor.id
        capture.decided_at = datetime.now(timezone.utc)
        session.add(capture)
        session.flush()
        audit.record(
            action="capture.rejected", entity_type="capture", entity_id=capture.id,
            before={"status": "proposed", "capture_type": capture.capture_type.value},
            after={"status": "rejected", "reason": reason},
        )
    return capture


def confirm_capture(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    capture: Capture,
    entity_type: MatchedEntityType | None = None,
    entity_id: uuid.UUID | None = None,
    quantity: Decimal | None = None,
    unit: str | None = None,
    # restock-only
    supplier_id: uuid.UUID | None = None,
    required_delivery_date: date | None = None,
    order_cycle: str | None = None,
    # eighty_six-only
    availability_status: MenuAvailabilityStatus = MenuAvailabilityStatus.unavailable,
    quantity_remaining: Decimal | None = None,
    # equipment_issue-only
    priority: EquipmentIssuePriority = EquipmentIssuePriority.medium,
    photos: str | None = None,
):
    if capture.status != CaptureStatus.proposed:
        raise CaptureAlreadyDecided(f"Capture {capture.id} is already {capture.status.value}")
    _raise_if_service_day_closed(session, capture.service_day_id)

    resolved_type = entity_type or capture.matched_entity_type
    resolved_id = entity_id or capture.matched_entity_id
    if resolved_type is None or resolved_id is None:
        raise UnresolvedCapture(
            "This capture has no confident match — supply entity_type and entity_id to confirm it"
        )
    _validate_matched_entity(session, venue=venue, entity_type=resolved_type, entity_id=resolved_id)

    resolved_quantity = quantity if quantity is not None else capture.extracted_quantity
    resolved_unit = unit or capture.extracted_unit
    action_type = ENTITY_TYPE_TO_CAPTURE_TYPE[resolved_type]

    before_snapshot = {
        "status": "proposed",
        "capture_type": capture.capture_type.value,
        "proposed_entity_id": str(capture.matched_entity_id) if capture.matched_entity_id else None,
    }

    if action_type == CaptureType.eighty_six:
        with audited_transaction(
            session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
            service_day_id=capture.service_day_id,
        ) as audit:
            event = MenuAvailabilityEvent(
                menu_item_id=resolved_id,
                service_day_id=capture.service_day_id,
                status=availability_status,
                quantity_remaining=quantity_remaining if quantity_remaining is not None else resolved_quantity,
                recorded_at=datetime.now(timezone.utc),
            )
            session.add(event)
            session.flush()
            audit.record(
                action="menu_availability_event.created", entity_type="menu_availability_event",
                entity_id=event.id,
                after={"menu_item_id": str(resolved_id), "status": availability_status.value},
            )

            capture.status = CaptureStatus.confirmed
            capture.capture_type = action_type
            capture.decided_by = actor.id
            capture.decided_at = datetime.now(timezone.utc)
            capture.matched_entity_type = resolved_type
            capture.matched_entity_id = resolved_id
            session.add(capture)
            session.flush()
            audit.record(
                action="capture.confirmed", entity_type="capture", entity_id=capture.id,
                before=before_snapshot,
                after={"status": "confirmed", "resulted_in": "menu_availability_event", "resulting_id": str(event.id)},
            )
        return capture, event

    if action_type == CaptureType.equipment_issue:
        with audited_transaction(
            session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
            service_day_id=capture.service_day_id,
        ) as audit:
            issue = EquipmentIssue(
                equipment_item_id=resolved_id,
                priority=priority,
                photos=photos,
                opened_at=datetime.now(timezone.utc),
            )
            session.add(issue)
            session.flush()
            audit.record(
                action="equipment_issue.logged", entity_type="equipment_issue", entity_id=issue.id,
                after={"equipment_item_id": str(resolved_id), "priority": priority.value},
            )

            capture.status = CaptureStatus.confirmed
            capture.capture_type = action_type
            capture.decided_by = actor.id
            capture.decided_at = datetime.now(timezone.utc)
            capture.matched_entity_type = resolved_type
            capture.matched_entity_id = resolved_id
            session.add(capture)
            session.flush()
            audit.record(
                action="capture.confirmed", entity_type="capture", entity_id=capture.id,
                before=before_snapshot,
                after={"status": "confirmed", "resulted_in": "equipment_issue", "resulting_id": str(issue.id)},
            )
        return capture, issue

    # action_type == CaptureType.restock
    if resolved_quantity is None:
        raise MissingConfirmationDetails("A restock confirmation needs a quantity")
    if supplier_id is None:
        ingredient = session.get(Ingredient, resolved_id)
        supplier_id = ingredient.preferred_supplier_id if ingredient else None
    if supplier_id is None:
        raise MissingConfirmationDetails(
            "A restock confirmation needs a supplier_id (this ingredient has no preferred_supplier_id)"
        )
    if required_delivery_date is None and order_cycle is None:
        raise MissingConfirmationDetails(
            "A restock confirmation needs required_delivery_date or order_cycle"
        )

    try:
        line_result = add_or_merge_line(
            session, venue=venue, actor=actor, supplier_id=supplier_id, ingredient_id=resolved_id,
            quantity=resolved_quantity, unit=resolved_unit,
            required_delivery_date=required_delivery_date, order_cycle=order_cycle,
        )
    except (UnknownSupplier, UnknownIngredient, MissingOrderIdentity) as exc:
        raise MissingConfirmationDetails(str(exc))

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id,
        service_day_id=capture.service_day_id,
    ) as audit:
        capture.status = CaptureStatus.confirmed
        capture.capture_type = action_type
        capture.decided_by = actor.id
        capture.decided_at = datetime.now(timezone.utc)
        capture.matched_entity_type = resolved_type
        capture.matched_entity_id = resolved_id
        session.add(capture)
        session.flush()
        audit.record(
            action="capture.confirmed", entity_type="capture", entity_id=capture.id,
            before=before_snapshot,
            after={
                "status": "confirmed", "resulted_in": "purchase_order_line",
                "resulting_id": str(line_result.line.id), "merged": line_result.merged,
            },
        )
    return capture, line_result.purchase_order
