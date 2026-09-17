from datetime import date
from decimal import Decimal

from app.models.audit import AuditEvent
from app.models.prep import PrepTask, PrepTaskStatus, PrepTemplateItem
from app.models.service_day import ServiceDay
from app.models.user import User
from app.services.onboarding_service import create_organisation_with_venue
from app.services.prep_service import (
    add_template_item,
    apply_prep_template,
    carry_forward_prep_tasks,
    create_prep_template,
    update_prep_task_status,
)
from app.services.service_day_service import get_or_create_service_day
from app.services.staffing_service import create_station


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_apply_template_creates_tasks_in_order(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="Weekday prep")
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg", priority=1,
    )
    add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Roast chicken", quantity=Decimal("20"), unit="kg", priority=2,
    )
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()

    tasks = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=service_day)

    assert [t.item for t in tasks] == ["Dice onions", "Roast chicken"]
    assert all(t.status == PrepTaskStatus.not_started for t in tasks)
    assert all(t.template_item_id is not None for t in tasks)


def test_editing_a_task_does_not_touch_the_template(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="Weekday prep")
    template_item = add_template_item(
        session, venue=venue, actor=owner, template=template, station=station,
        item="Dice onions", quantity=Decimal("5"), unit="kg",
    )
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=service_day)[0]

    update_prep_task_status(session, venue=venue, actor=owner, task=task, status=PrepTaskStatus.done)

    session.refresh(template_item)
    assert template_item.item == "Dice onions"  # untouched


def test_update_status_writes_audit_event(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="X", quantity=Decimal("1"), unit="kg")
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=service_day)[0]

    update_prep_task_status(session, venue=venue, actor=owner, task=task, status=PrepTaskStatus.in_progress)

    event = session.query(AuditEvent).filter_by(action="prep_task.status_changed").one()
    assert event.before_data == {"status": "not_started"}
    assert event.after_data == {"status": "in_progress"}


def test_carry_forward_only_moves_not_done_tasks(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="Done task", quantity=Decimal("1"), unit="kg")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="Not done task", quantity=Decimal("1"), unit="kg")
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    tasks = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day1)
    done_task, not_done_task = tasks
    update_prep_task_status(session, venue=venue, actor=owner, task=done_task, status=PrepTaskStatus.done)

    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 2))
    session.commit()
    carried = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)

    assert len(carried) == 1
    assert carried[0].item == "Not done task"
    assert carried[0].carried_from_task_id == not_done_task.id
    assert carried[0].carry_count == 1

    session.refresh(not_done_task)
    assert not_done_task.carried_to_task_id == carried[0].id
    session.refresh(done_task)
    assert done_task.carried_to_task_id is None  # done tasks are never carried


def test_carry_forward_is_idempotent_no_duplicate(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="X", quantity=Decimal("1"), unit="kg")
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day1)
    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 2))
    session.commit()

    first = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)
    second = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)

    assert len(first) == 1
    assert second == []
    assert session.query(PrepTask).filter_by(service_day_id=day2.id).count() == 1


def test_carry_forward_chain_never_branches_carry_count_climbs(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="X", quantity=Decimal("1"), unit="kg")
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    task_day1 = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day1)[0]

    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 2))
    session.commit()
    task_day2 = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)[0]
    assert task_day2.carry_count == 1

    day3 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 3))
    session.commit()
    task_day3 = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day2, to_service_day=day3)[0]
    assert task_day3.carry_count == 2
    assert task_day3.carried_from_task_id == task_day2.id

    # exactly one live (uncarried) task in the whole chain
    assert session.query(PrepTask).filter_by(carried_to_task_id=None).count() == 1


def test_carry_forward_with_nothing_to_move_still_persists_lazy_service_day(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="X", quantity=Decimal("1"), unit="kg")
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day1)[0]
    update_prep_task_status(session, venue=venue, actor=owner, task=task, status=PrepTaskStatus.done)

    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 2))  # flushed, not committed
    carried = carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)

    assert carried == []
    # New session-level check: the lazily-created day2 must have persisted
    # even though there was nothing to carry.
    session.expire_all()
    assert session.get(ServiceDay, day2.id) is not None
