from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.audit import AuditEvent
from app.models.user import User
from app.services import email_service
from app.services.capture_service import confirm_capture, create_capture
from app.services.catalog_service import create_equipment_item, create_ingredient, create_supplier
from app.services.notification_service import (
    ORDER_CUTOFF_ACTION,
    STALE_EQUIPMENT_ACTION,
    UNFILLED_SHIFT_ACTION,
    run_notification_checks,
)
from app.services.onboarding_service import create_organisation_with_venue
from app.services.staffing_service import create_coverage_rule, create_station
from app.services.supplier_order_service import add_or_merge_line

SYDNEY = ZoneInfo("Australia/Sydney")


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


@pytest.fixture(autouse=True)
def _reset_email_sender():
    original = email_service.EMAIL_SENDER
    yield
    email_service.EMAIL_SENDER = original


def _capture_sent_emails() -> list[email_service.EmailMessage]:
    sent: list[email_service.EmailMessage] = []

    def fake_sender(message: email_service.EmailMessage) -> email_service.SentEmail:
        sent.append(message)
        return email_service.SentEmail(message_id="test-message-id", to=message.to)

    email_service.EMAIL_SENDER = fake_sender
    return sent


# --- Order cut-off approaching ---------------------------------------------


def test_approaching_cutoff_notifies_management(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co",
        order_days="mon,thu", cutoff_time=time(14, 0),
    )
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 5),
    )
    # 2026-06-01 is a Monday; 6am same day puts the 14:00 cutoff ~8h away.
    as_of = datetime(2026, 6, 1, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)

    results = run_notification_checks(session, venue=venue, as_of=as_of)

    cutoff_results = [r for r in results if r.action == ORDER_CUTOFF_ACTION]
    assert len(cutoff_results) == 1
    assert cutoff_results[0].recipients == ["owner@example.com"]
    assert [m.to for m in sent] == ["owner@example.com"]
    assert session.query(AuditEvent).filter_by(action=ORDER_CUTOFF_ACTION).count() == 1


def test_approaching_cutoff_outside_window_does_not_notify(session):
    _capture_sent_emails()
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co",
        order_days="mon", cutoff_time=time(14, 0),
    )
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 12),
    )
    # Far from any Monday 14:00 cutoff.
    as_of = datetime(2026, 6, 2, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)  # Tuesday

    results = run_notification_checks(session, venue=venue, as_of=as_of)

    assert [r for r in results if r.action == ORDER_CUTOFF_ACTION] == []


def test_approaching_cutoff_is_not_re_sent_within_the_same_service_day(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", contact_email="o@fresh.co",
        order_days="mon,thu", cutoff_time=time(14, 0),
    )
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    add_or_merge_line(
        session, venue=venue, actor=owner, supplier_id=supplier.id, ingredient_id=onions.id,
        quantity=Decimal("5"), required_delivery_date=date(2026, 6, 5),
    )
    as_of = datetime(2026, 6, 1, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)

    first = run_notification_checks(session, venue=venue, as_of=as_of)
    second = run_notification_checks(session, venue=venue, as_of=as_of + timedelta(hours=1))

    assert len([r for r in first if r.action == ORDER_CUTOFF_ACTION]) == 1
    assert [r for r in second if r.action == ORDER_CUTOFF_ACTION] == []
    assert len(sent) == 1  # only the first run actually emailed anyone
    assert session.query(AuditEvent).filter_by(action=ORDER_CUTOFF_ACTION).count() == 1


# --- Unfilled shift within 48h ---------------------------------------------


def test_unfilled_shift_within_48h_notifies_management(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    # 2026-06-01 is a Monday (day_of_week=0); nobody is rostered on, so this
    # rule's minimum_staff is never met.
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(9, 0), window_end=time(17, 0), minimum_staff=2,
    )
    as_of = datetime(2026, 6, 1, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)  # window starts in ~3h

    results = run_notification_checks(session, venue=venue, as_of=as_of)

    unfilled_results = [r for r in results if r.action == UNFILLED_SHIFT_ACTION]
    assert len(unfilled_results) == 1
    assert unfilled_results[0].recipients == ["owner@example.com"]
    assert [m.to for m in sent] == ["owner@example.com"]


def test_unfilled_shift_more_than_48h_away_does_not_notify(session):
    _capture_sent_emails()
    owner, venue = _owner_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(9, 0), window_end=time(17, 0), minimum_staff=2,
    )
    # Thursday — the next Monday's window is more than 48h away, and
    # Thu/Fri/Sat (the candidate business dates within the 48h horizon)
    # never match this rule's Monday-only day_of_week.
    as_of = datetime(2026, 5, 28, 6, 0, tzinfo=SYDNEY).astimezone(timezone.utc)

    results = run_notification_checks(session, venue=venue, as_of=as_of)

    assert [r for r in results if r.action == UNFILLED_SHIFT_ACTION] == []


# --- Equipment issue open >24h ----------------------------------------------


def test_stale_equipment_issue_notifies_management(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_venue(session)
    create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")
    _, issue = confirm_capture(session, venue=venue, actor=owner, capture=capture)

    as_of = datetime.now(timezone.utc)
    issue.opened_at = as_of - timedelta(hours=25)
    session.add(issue)
    session.commit()

    results = run_notification_checks(session, venue=venue, as_of=as_of)

    stale_results = [r for r in results if r.action == STALE_EQUIPMENT_ACTION]
    assert len(stale_results) == 1
    assert stale_results[0].entity_id == issue.id
    assert [m.to for m in sent] == ["owner@example.com"]


def test_equipment_issue_under_24h_does_not_notify(session):
    _capture_sent_emails()
    owner, venue = _owner_venue(session)
    create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")
    confirm_capture(session, venue=venue, actor=owner, capture=capture)

    results = run_notification_checks(session, venue=venue, as_of=datetime.now(timezone.utc))

    assert [r for r in results if r.action == STALE_EQUIPMENT_ACTION] == []
