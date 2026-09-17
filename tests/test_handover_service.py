from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit import AuditEvent
from app.models.equipment import EquipmentIssue, EquipmentIssuePriority
from app.models.handover import Handover, HandoverItem
from app.models.menu import MenuAvailabilityStatus
from app.models.prep import PrepTaskStatus
from app.models.purchase_order import DeliveryIssueType, PurchaseOrderStatus
from app.models.service_day import ServiceDayStatus
from app.models.user import User
from app.services.capture_service import create_capture
from app.services.catalog_service import create_equipment_item, create_ingredient, create_menu_item, create_supplier
from app.services.handover_service import (
    ServiceDayNotClosed,
    ServiceDayNotOpen,
    close_service_day,
    get_handover_for_service_day,
    reopen_service_day,
    set_handover_item_included,
)
from app.services.onboarding_service import create_organisation_with_venue
from app.services.prep_service import add_template_item, apply_prep_template, create_prep_template, update_prep_task_status
from app.services.service_day_service import ServiceDayIsClosed, get_or_create_service_day, open_service_day
from app.services.staffing_service import create_station
from app.services.supplier_order_service import add_or_merge_line, log_delivery_issue, mark_delivery


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def _opened_day(session, venue, owner, business_date=date(2026, 6, 1)):
    day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    session.commit()
    return open_service_day(session, service_day=day, venue=venue, actor=owner)


def test_close_requires_open_service_day(session):
    owner, venue = _owner_venue(session)
    day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()  # still "planned" — never opened

    with pytest.raises(ServiceDayNotOpen):
        close_service_day(session, venue=venue, actor=owner, service_day=day)


def test_close_flips_status_and_records_timestamp(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)

    handover = close_service_day(session, venue=venue, actor=owner, service_day=day, note="quiet night")

    session.refresh(day)
    assert day.status == ServiceDayStatus.closed
    assert day.closed_at is not None
    assert handover.note == "quiet night"
    assert handover.closed_by == owner.id
    assert handover.time_to_close_seconds >= 0

    event = session.query(AuditEvent).filter_by(action="service_day.closed").one()
    assert event.before_data == {"status": "open"}
    assert event.after_data == {"status": "closed"}
    saved_event = session.query(AuditEvent).filter_by(action="handover.saved").one()
    assert saved_event.after_data["note"] == "quiet night"
    # Epic 11 metrics wiring: "logged with open/close timestamps"
    assert saved_event.after_data["opened_at"] is not None
    assert saved_event.after_data["closed_at"] is not None


def test_close_populates_all_six_handover_item_categories(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)

    # 1. not-done PrepTask
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg",
    )
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)[0]

    # 2. today's MenuAvailabilityEvent (via an eighty_six capture confirm)
    salmon = create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    eighty_six_capture = create_capture(
        session, venue=venue, actor=owner, raw_text="86 the grilled salmon", business_date=day.business_date,
    )
    from app.services.capture_service import confirm_capture
    confirm_capture(session, venue=venue, actor=owner, capture=eighty_six_capture)

    # 3. open EquipmentIssue (via an equipment_issue capture confirm)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    equip_capture = create_capture(
        session, venue=venue, actor=owner, raw_text="the stand mixer is broken", business_date=day.business_date,
    )
    confirm_capture(session, venue=venue, actor=owner, capture=equip_capture)

    # 4. open DeliveryIssue + draft/sent PurchaseOrder
    supplier = create_supplier(session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co")
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    line_result = add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("10"), required_delivery_date=date(2026, 6, 2),
    )
    draft_order = line_result.purchase_order
    mark_delivery(session, venue=venue, actor=owner, purchase_order=draft_order, partial=False)
    log_delivery_issue(
        session, venue=venue, actor=owner, purchase_order=draft_order,
        issue_type=DeliveryIssueType.short_delivery,
    )

    # 6. unparsed Capture
    unparsed = create_capture(
        session, venue=venue, actor=owner, raw_text="the walk-in fridge door sticks", business_date=day.business_date,
    )
    assert unparsed.capture_type.value == "unparsed"

    handover = close_service_day(session, venue=venue, actor=owner, service_day=day)

    item_types = {item.item_type for item in handover.items}
    assert item_types == {
        "prep_task", "menu_availability_event", "equipment_issue",
        "delivery_issue", "purchase_order", "capture",
    }
    prep_item = next(i for i in handover.items if i.item_type == "prep_task")
    assert prep_item.prep_task_id == task.id
    assert all(item.included for item in handover.items)


def test_done_prep_tasks_are_not_included_in_handover(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg",
    )
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)[0]
    update_prep_task_status(session, venue=venue, actor=owner, task=task, status=PrepTaskStatus.done)

    handover = close_service_day(session, venue=venue, actor=owner, service_day=day)

    assert handover.items == []


def test_toggling_included_never_touches_underlying_record(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg",
    )
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)[0]
    handover = close_service_day(session, venue=venue, actor=owner, service_day=day)
    item = handover.items[0]

    set_handover_item_included(session, venue=venue, actor=owner, handover_item=item, included=False)

    session.refresh(item)
    assert item.included is False
    session.refresh(task)
    assert task.status == PrepTaskStatus.not_started  # untouched
    event = session.query(AuditEvent).filter_by(action="handover_item.included_toggled").one()
    assert event.before_data == {"included": True}
    assert event.after_data == {"included": False}


def test_handover_item_check_constraint_rejects_zero_or_two_references(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    handover = close_service_day(session, venue=venue, actor=owner, service_day=day)

    session.add(HandoverItem(handover_id=handover.id))  # zero references set
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="X", quantity=Decimal("1"), unit="kg",
    )
    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 5))
    session.commit()
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day2)[0]
    salmon = create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    from app.models.menu import MenuAvailabilityEvent
    event = MenuAvailabilityEvent(
        menu_item_id=salmon.id, service_day_id=day2.id, status=MenuAvailabilityStatus.unavailable,
        recorded_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()

    session.add(HandoverItem(handover_id=handover.id, prep_task_id=task.id, menu_availability_event_id=event.id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_reopen_requires_closed_service_day(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)

    with pytest.raises(ServiceDayNotClosed):
        reopen_service_day(session, venue=venue, actor=owner, service_day=day, reason="testing")


def test_reopen_flips_status_and_records_reason(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    close_service_day(session, venue=venue, actor=owner, service_day=day)

    reopened = reopen_service_day(session, venue=venue, actor=owner, service_day=day, reason="chef forgot a delivery issue")

    assert reopened.status == ServiceDayStatus.open
    event = session.query(AuditEvent).filter_by(action="service_day.reopened").one()
    assert event.after_data["reason"] == "chef forgot a delivery issue"
    assert event.actor_user_id == owner.id


def test_reclosing_after_reopen_updates_same_handover_row_not_a_duplicate(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg",
    )
    apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)
    first_handover = close_service_day(session, venue=venue, actor=owner, service_day=day, note="first close")
    first_id = first_handover.id

    reopen_service_day(session, venue=venue, actor=owner, service_day=day, reason="need to add a late note")
    # Sanctioned late-entry path: a brand new task added after close.
    apply_prep_template(
        session, venue=venue, actor=owner, template=template, service_day=day, added_after_close=True,
    )
    second_handover = close_service_day(session, venue=venue, actor=owner, service_day=day, note="second close")

    assert second_handover.id == first_id
    assert session.query(Handover).filter_by(service_day_id=day.id).count() == 1
    assert second_handover.note == "second close"
    # Fresh items: 2 prep tasks now not-done (original + late-entry one).
    assert len(second_handover.items) == 2


def test_apply_template_against_closed_day_is_rejected_without_override(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="X", quantity=Decimal("1"), unit="kg",
    )
    close_service_day(session, venue=venue, actor=owner, service_day=day)

    with pytest.raises(ServiceDayIsClosed):
        apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)


def test_apply_template_against_closed_day_succeeds_with_override_and_stores_flag(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="X", quantity=Decimal("1"), unit="kg",
    )
    close_service_day(session, venue=venue, actor=owner, service_day=day)

    tasks = apply_prep_template(
        session, venue=venue, actor=owner, template=template, service_day=day, added_after_close=True,
    )

    assert tasks[0].added_after_close is True


def test_editing_existing_prep_task_on_closed_day_is_always_rejected(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="X", quantity=Decimal("1"), unit="kg",
    )
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)[0]
    close_service_day(session, venue=venue, actor=owner, service_day=day)

    with pytest.raises(ServiceDayIsClosed):
        update_prep_task_status(session, venue=venue, actor=owner, task=task, status=PrepTaskStatus.done)


def test_create_capture_against_closed_day_is_rejected_without_override(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    close_service_day(session, venue=venue, actor=owner, service_day=day)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")

    with pytest.raises(ServiceDayIsClosed):
        create_capture(
            session, venue=venue, actor=owner, raw_text="86 the grilled salmon", business_date=day.business_date,
        )


def test_create_capture_against_closed_day_succeeds_with_override(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    close_service_day(session, venue=venue, actor=owner, service_day=day)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")

    capture = create_capture(
        session, venue=venue, actor=owner, raw_text="86 the grilled salmon",
        business_date=day.business_date, added_after_close=True,
    )

    assert capture.added_after_close is True


def test_deciding_on_existing_capture_after_close_is_rejected(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    capture = create_capture(
        session, venue=venue, actor=owner, raw_text="86 the grilled salmon", business_date=day.business_date,
    )
    close_service_day(session, venue=venue, actor=owner, service_day=day)

    from app.services.capture_service import confirm_capture
    with pytest.raises(ServiceDayIsClosed):
        confirm_capture(session, venue=venue, actor=owner, capture=capture)


def test_get_handover_for_service_day(session):
    owner, venue = _owner_venue(session)
    day = _opened_day(session, venue, owner)

    assert get_handover_for_service_day(session, service_day_id=day.id) is None

    handover = close_service_day(session, venue=venue, actor=owner, service_day=day)

    found = get_handover_for_service_day(session, service_day_id=day.id)
    assert found.id == handover.id
