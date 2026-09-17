from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditEvent
from app.models.capture import CaptureStatus, CaptureType, MatchedEntityType
from app.models.equipment import EquipmentIssue, EquipmentIssuePriority
from app.models.menu import MenuAvailabilityEvent, MenuAvailabilityStatus
from app.models.purchase_order import PurchaseOrder
from app.models.user import User
from app.services.capture_service import (
    CaptureAlreadyDecided,
    MissingConfirmationDetails,
    UnknownMatchedEntity,
    UnresolvedCapture,
    confirm_capture,
    create_capture,
    reject_capture,
)
from app.services.catalog_service import create_equipment_item, create_ingredient, create_menu_item, create_supplier
from app.services.onboarding_service import create_organisation_with_venue


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_create_capture_persists_classification(session):
    owner, venue = _owner_venue(session)
    onions = create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")

    capture = create_capture(session, venue=venue, actor=owner, raw_text="running low on yellow onions, need 10kg")

    assert capture.status == CaptureStatus.proposed
    assert capture.capture_type == CaptureType.restock
    assert capture.matched_entity_id == onions.id
    assert capture.service_day_id is not None


def test_create_capture_writes_audit_event(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")

    create_capture(session, venue=venue, actor=owner, raw_text="running low on yellow onions, 10kg")

    event = session.query(AuditEvent).filter_by(action="capture.proposed").one()
    assert event.after_data["capture_type"] == "restock"


def test_confirm_eighty_six_creates_menu_availability_event_scoped_to_service_day(session):
    owner, venue = _owner_venue(session)
    salmon = create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")

    confirmed, event = confirm_capture(session, venue=venue, actor=owner, capture=capture)

    assert confirmed.status == CaptureStatus.confirmed
    assert confirmed.decided_by == owner.id
    assert isinstance(event, MenuAvailabilityEvent)
    assert event.menu_item_id == salmon.id
    assert event.service_day_id == capture.service_day_id
    assert event.status == MenuAvailabilityStatus.unavailable


def test_confirm_equipment_issue_creates_equipment_issue(session):
    owner, venue = _owner_venue(session)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")

    confirmed, issue = confirm_capture(
        session, venue=venue, actor=owner, capture=capture, priority=EquipmentIssuePriority.high,
        photos="photo://stub.jpg",
    )

    assert isinstance(issue, EquipmentIssue)
    assert issue.equipment_item_id == mixer.id
    assert issue.priority == EquipmentIssuePriority.high
    assert issue.photos == "photo://stub.jpg"
    assert confirmed.status == CaptureStatus.confirmed


def test_confirm_restock_calls_add_or_merge_line(session):
    owner, venue = _owner_venue(session)
    supplier = create_supplier(session, venue=venue, actor=owner, name="Fresh Co")
    onions = create_ingredient(
        session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack",
        preferred_supplier_id=supplier.id,
    )
    capture = create_capture(session, venue=venue, actor=owner, raw_text="running low on yellow onions, need 10kg")

    confirmed, purchase_order = confirm_capture(
        session, venue=venue, actor=owner, capture=capture, required_delivery_date=date(2026, 6, 10),
    )

    assert isinstance(purchase_order, PurchaseOrder)
    assert len(purchase_order.lines) == 1
    assert purchase_order.lines[0].ingredient_id == onions.id
    assert purchase_order.lines[0].quantity == Decimal("10")
    assert purchase_order.supplier_id == supplier.id  # defaulted from preferred_supplier_id


def test_confirm_restock_without_supplier_or_preferred_supplier_fails(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="running low on yellow onions, need 10kg")

    with pytest.raises(MissingConfirmationDetails):
        confirm_capture(session, venue=venue, actor=owner, capture=capture, required_delivery_date=date(2026, 6, 10))


def test_unparsed_capture_requires_explicit_resolution(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the walk-in fridge door sticks")

    assert capture.capture_type == CaptureType.unparsed
    with pytest.raises(UnresolvedCapture):
        confirm_capture(session, venue=venue, actor=owner, capture=capture)


def test_unparsed_capture_confirmed_with_explicit_entity(session):
    owner, venue = _owner_venue(session)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Combi Oven")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="something in the kitchen needs attention")
    assert capture.capture_type == CaptureType.unparsed

    confirmed, issue = confirm_capture(
        session, venue=venue, actor=owner, capture=capture,
        entity_type=MatchedEntityType.equipment_item, entity_id=mixer.id,
    )

    assert confirmed.capture_type == CaptureType.equipment_issue
    assert issue.equipment_item_id == mixer.id


def test_confirm_with_unknown_entity_id_raises(session):
    owner, venue = _owner_venue(session)
    capture = create_capture(session, venue=venue, actor=owner, raw_text="something broke")
    import uuid

    with pytest.raises(UnknownMatchedEntity):
        confirm_capture(
            session, venue=venue, actor=owner, capture=capture,
            entity_type=MatchedEntityType.equipment_item, entity_id=uuid.uuid4(),
        )


def test_cannot_confirm_twice(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")
    confirm_capture(session, venue=venue, actor=owner, capture=capture)

    with pytest.raises(CaptureAlreadyDecided):
        confirm_capture(session, venue=venue, actor=owner, capture=capture)


def test_reject_capture_logs_decision(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")

    rejected = reject_capture(session, venue=venue, actor=owner, capture=capture, reason="false alarm")

    assert rejected.status == CaptureStatus.rejected
    assert rejected.decided_by == owner.id
    event = session.query(AuditEvent).filter_by(action="capture.rejected").one()
    assert event.after_data["reason"] == "false alarm"


def test_cannot_reject_already_decided_capture(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")
    reject_capture(session, venue=venue, actor=owner, capture=capture)

    with pytest.raises(CaptureAlreadyDecided):
        reject_capture(session, venue=venue, actor=owner, capture=capture)


def test_confirm_writes_audit_event_with_before_and_after(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")

    confirm_capture(session, venue=venue, actor=owner, capture=capture)

    event = session.query(AuditEvent).filter_by(action="capture.confirmed").one()
    assert event.before_data["status"] == "proposed"
    assert event.after_data["status"] == "confirmed"
    assert event.after_data["resulted_in"] == "menu_availability_event"
