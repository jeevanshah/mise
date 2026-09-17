from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models.attendance import AttendanceStatus
from app.models.audit import AuditEvent
from app.models.menu import MenuAvailabilityStatus
from app.models.user import User
from app.services.attendance_service import log_attendance_as_chef
from app.services.capture_service import confirm_capture, create_capture
from app.services.catalog_service import create_equipment_item, create_ingredient, create_menu_item, create_supplier
from app.services.chef_brief_service import compute_approaching_cutoffs, get_chef_brief
from app.services.handover_service import close_service_day
from app.services.onboarding_service import create_organisation_with_venue
from app.services.prep_service import add_template_item, apply_prep_template, carry_forward_prep_tasks, create_prep_template, update_prep_task_status
from app.services.roster_service import create_shift, publish_shift
from app.services.service_day_service import get_or_create_service_day, open_service_day
from app.services.staffing_service import create_coverage_rule, create_staff, create_station
from app.models.prep import PrepTaskStatus

SYDNEY = ZoneInfo("Australia/Sydney")


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def _dt(y, m, d, h, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=SYDNEY)


def test_defaults_to_current_service_day_and_lazily_creates_it(session):
    owner, venue = _owner_venue(session)

    brief = get_chef_brief(session, venue=venue, actor=owner)

    from app.services.service_day_service import resolve_business_date
    assert brief.business_date == resolve_business_date(venue)


def test_rostered_staff_includes_draft_and_published_not_cancelled(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    alex = create_staff(session, venue=venue, actor=owner, name="Alex")
    sam = create_staff(session, venue=venue, actor=owner, name="Sam")
    shift1 = create_shift(
        session, venue=venue, actor=owner, station=station, staff=alex,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    publish_shift(session, venue=venue, actor=owner, shift=shift1)
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=sam,
        start_at=_dt(2026, 6, 1, 10), end_at=_dt(2026, 6, 1, 18),
    )  # left as draft

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))

    names = {row.staff_name for row in brief.rostered_staff}
    assert names == {"Alex", "Sam"}
    assert all(row.attendance_status is None for row in brief.rostered_staff)  # "expected"


def test_rostered_staff_excludes_cancelled_and_reflects_attendance(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    alex = create_staff(session, venue=venue, actor=owner, name="Alex")
    present_shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=alex,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    log_attendance_as_chef(session, venue=venue, actor=owner, shift=present_shift, status=AttendanceStatus.present)

    sam = create_staff(session, venue=venue, actor=owner, name="Sam")
    from app.services.roster_service import cancel_shift
    cancelled_shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=sam,
        start_at=_dt(2026, 6, 1, 10), end_at=_dt(2026, 6, 1, 18),
    )
    cancel_shift(session, venue=venue, actor=owner, shift=cancelled_shift)

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))

    assert len(brief.rostered_staff) == 1
    assert brief.rostered_staff[0].staff_name == "Alex"
    assert brief.rostered_staff[0].attendance_status == "present"


def test_coverage_gaps_matches_compute_coverage_warnings(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station, day_of_week=0,  # Monday
        window_start=time(9, 0), window_end=time(17, 0), minimum_staff=2,
    )
    alex = create_staff(session, venue=venue, actor=owner, name="Alex")
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=alex,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),  # 2026-06-01 is a Monday
    )

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))

    assert len(brief.coverage_gaps) == 1
    assert brief.coverage_gaps[0].scheduled_staff == 1
    assert brief.coverage_gaps[0].minimum_staff == 2


def test_priority_open_prep_tasks_excludes_done_orders_by_priority(session):
    owner, venue = _owner_venue(session)
    day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="Low", quantity=Decimal("1"), unit="kg", priority=1)
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="High", quantity=Decimal("1"), unit="kg", priority=5)
    low_task, high_task = apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day)
    update_prep_task_status(session, venue=venue, actor=owner, task=low_task, status=PrepTaskStatus.done)

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))

    assert [t.item for t in brief.priority_open_prep_tasks] == ["High"]


def test_carried_forward_tasks_surfaces_on_the_new_days_brief(session):
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    template = create_prep_template(session, venue=venue, actor=owner, name="T")
    add_template_item(session, venue=venue, actor=owner, template=template, station=station, item="X", quantity=Decimal("1"), unit="kg")
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    apply_prep_template(session, venue=venue, actor=owner, template=template, service_day=day1)
    day2 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 2))
    session.commit()
    carry_forward_prep_tasks(session, venue=venue, actor=owner, from_service_day=day1, to_service_day=day2)

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 2))

    assert len(brief.carried_forward_tasks) == 1
    assert brief.carried_forward_tasks[0].item == "X"


def test_open_equipment_issues_are_venue_wide(session):
    owner, venue = _owner_venue(session)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")
    confirm_capture(session, venue=venue, actor=owner, capture=capture)

    brief = get_chef_brief(session, venue=venue, actor=owner)

    assert len(brief.open_equipment_issues) == 1
    assert brief.open_equipment_issues[0].equipment_item_id == mixer.id


def test_unavailable_or_low_menu_items_excludes_available_and_uses_latest(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")
    steak = create_menu_item(session, venue=venue, actor=owner, name="Ribeye Steak")

    capture1 = create_capture(session, venue=venue, actor=owner, raw_text="86 the grilled salmon")
    confirm_capture(session, venue=venue, actor=owner, capture=capture1)

    # Steak: 86'd, then explicitly brought back — latest status wins (available, excluded).
    capture2 = create_capture(session, venue=venue, actor=owner, raw_text="86 the ribeye steak")
    confirm_capture(session, venue=venue, actor=owner, capture=capture2)
    from app.models.menu import MenuAvailabilityEvent
    session.add(MenuAvailabilityEvent(
        menu_item_id=steak.id, service_day_id=capture2.service_day_id,
        status=MenuAvailabilityStatus.available, recorded_at=datetime.now(timezone.utc),
    ))
    session.commit()

    brief = get_chef_brief(session, venue=venue, actor=owner)

    names = {item.menu_item_name for item in brief.unavailable_or_low_menu_items}
    assert names == {"Grilled Salmon"}


def test_yesterdays_handover_none_when_no_service_day_or_no_handover(session):
    owner, venue = _owner_venue(session)

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 2))
    assert brief.yesterdays_handover is None

    get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    brief_again = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 2))
    assert brief_again.yesterdays_handover is None  # day exists but was never closed


def test_yesterdays_handover_populated_after_close(session):
    owner, venue = _owner_venue(session)
    day1 = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    day1 = open_service_day(session, service_day=day1, venue=venue, actor=owner)
    handover = close_service_day(session, venue=venue, actor=owner, service_day=day1, note="handoff note")

    brief = get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 2))

    assert brief.yesterdays_handover is not None
    assert brief.yesterdays_handover.id == handover.id
    assert brief.yesterdays_handover.note == "handoff note"


def test_opening_the_brief_writes_an_audit_event_every_time_no_dedup(session):
    owner, venue = _owner_venue(session)

    get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))
    get_chef_brief(session, venue=venue, actor=owner, business_date=date(2026, 6, 1))

    events = session.query(AuditEvent).filter_by(action="brief.opened").all()
    assert len(events) == 2
    assert all(e.actor_user_id == owner.id for e in events)


def test_approaching_cutoff_within_window_is_surfaced(session):
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co",
        order_days="mon,thu", cutoff_time=time(14, 0),
    )
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    from app.services.supplier_order_service import add_or_merge_line
    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 5),
    )
    # 2026-06-01 is a Monday; as_of 6am same day means the 14:00 cutoff is
    # ~8 hours away — well within the 24h window.
    as_of = datetime(2026, 6, 1, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)

    approaching = compute_approaching_cutoffs(session, venue=venue, as_of=as_of)

    assert len(approaching) == 1
    assert approaching[0].supplier_id == supplier.id


def test_approaching_cutoff_outside_window_is_not_surfaced(session):
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co",
        order_days="mon", cutoff_time=time(14, 0),
    )
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    from app.services.supplier_order_service import add_or_merge_line
    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 12),
    )
    # Far from any Monday 14:00 cutoff.
    as_of = datetime(2026, 6, 2, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)  # Tuesday

    approaching = compute_approaching_cutoffs(session, venue=venue, as_of=as_of)

    assert approaching == []


def test_approaching_cutoff_ignores_empty_drafts_and_unconfigured_suppliers(session):
    owner, venue = _owner_venue(session)
    from app.services.supplier_order_service import get_or_create_draft_purchase_order
    no_cutoff_supplier = create_supplier(session, venue=venue, actor=owner, name="No Cutoff Co")
    get_or_create_draft_purchase_order(
        session, venue=venue, supplier=no_cutoff_supplier, required_delivery_date=date(2026, 6, 5),
    )
    session.commit()

    configured_supplier = create_supplier(
        session, venue=venue, actor=owner, name="Configured Co",
        order_days="mon", cutoff_time=time(14, 0),
    )
    get_or_create_draft_purchase_order(
        session, venue=venue, supplier=configured_supplier, required_delivery_date=date(2026, 6, 5),
    )  # no lines added — empty draft
    session.commit()

    as_of = datetime(2026, 6, 1, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)
    approaching = compute_approaching_cutoffs(session, venue=venue, as_of=as_of)

    assert approaching == []
