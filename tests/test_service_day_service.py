from datetime import date, datetime, time, timezone

import pytest

from app.models.audit import AuditEvent
from app.models.service_day import ServiceDay, ServiceDayStatus
from app.models.user import User
from app.services.onboarding_service import create_organisation_with_venue, update_venue_settings
from app.services.service_day_service import (
    CannotOpenClosedServiceDay,
    get_or_create_service_day,
    open_service_day,
    resolve_business_date,
)


def _owner_and_venue(session, timezone_name="Australia/Sydney"):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner",
        timezone=timezone_name,
    )
    return owner, venue


# --- resolve_business_date --------------------------------------------


def test_dinner_service_ending_1am_is_still_the_prior_business_date(session):
    """The exact scenario from the locked spec: a Friday dinner service
    ending 1am Saturday, default 04:00 boundary, is business_date = Friday."""
    owner, venue = _owner_and_venue(session)  # default boundary 04:00, Sydney

    # 1am Saturday Jan 3 2026 Sydney time = Friday Jan 2 2026 in UTC terms
    # doesn't matter — pass a UTC instant that is 1am Saturday in Sydney.
    # Sydney is UTC+11 in January (DST). 1am Sat local = 14:00 UTC Friday.
    saturday_1am_sydney_in_utc = datetime(2026, 1, 2, 14, 0, tzinfo=timezone.utc)

    business_date = resolve_business_date(venue, at=saturday_1am_sydney_in_utc)
    assert business_date == date(2026, 1, 2)  # the Friday


def test_time_after_boundary_is_the_same_calendar_day(session):
    owner, venue = _owner_and_venue(session)
    # 10am Saturday Sydney = 23:00 UTC Friday
    ten_am_saturday_sydney_in_utc = datetime(2026, 1, 2, 23, 0, tzinfo=timezone.utc)
    business_date = resolve_business_date(venue, at=ten_am_saturday_sydney_in_utc)
    assert business_date == date(2026, 1, 3)  # the Saturday


def test_exactly_at_boundary_counts_as_the_new_day(session):
    owner, venue = _owner_and_venue(session)
    # Exactly 04:00 Sydney = 17:00 UTC the prior day (Sydney is UTC+11 in Jan)
    exactly_boundary_utc = datetime(2026, 1, 2, 17, 0, tzinfo=timezone.utc)
    business_date = resolve_business_date(venue, at=exactly_boundary_utc)
    assert business_date == date(2026, 1, 3)


def test_resolve_business_date_uses_the_venues_own_timezone_not_utc(session):
    owner, venue_sydney = _owner_and_venue(session, timezone_name="Australia/Sydney")
    _, venue_perth, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Perth Co", venue_name="Perth Diner",
        timezone="Australia/Perth",
    )
    # Perth has no DST and is UTC+8; Sydney is UTC+11 in January.
    # Pick a UTC instant that is 2am in Sydney (before boundary -> prior day)
    # but 11pm the PRIOR day in Perth (also before midnight, still counts by
    # boundary rule relative to Perth's own local date).
    moment = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)  # 2am Sat Sydney / 11pm Fri Perth

    sydney_date = resolve_business_date(venue_sydney, at=moment)
    perth_date = resolve_business_date(venue_perth, at=moment)

    assert sydney_date == date(2026, 1, 2)  # Friday (2am < 4am boundary)
    assert perth_date == date(2026, 1, 2)  # Friday (11pm, same calendar day)


def test_resolve_business_date_requires_timezone_aware_input(session):
    owner, venue = _owner_and_venue(session)
    with pytest.raises(ValueError):
        resolve_business_date(venue, at=datetime(2026, 1, 2, 10, 0))  # naive


def test_resolve_business_date_respects_a_custom_boundary(session):
    owner, venue = _owner_and_venue(session)
    update_venue_settings(session, venue=venue, actor=owner, business_day_boundary=time(6, 0))
    session.refresh(venue)

    # 5am Sydney (after the old 4am boundary, before the new 6am one)
    five_am_sydney_utc = datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc)
    business_date = resolve_business_date(venue, at=five_am_sydney_utc)
    assert business_date == date(2026, 1, 1)  # still the prior day under the new boundary


# --- get_or_create_service_day -----------------------------------------


def test_get_or_create_is_lazy_and_idempotent(session):
    owner, venue = _owner_and_venue(session)
    target_date = date(2026, 6, 1)

    assert session.query(ServiceDay).count() == 0
    first = get_or_create_service_day(session, venue=venue, business_date=target_date)
    session.commit()
    assert first.status == ServiceDayStatus.planned

    second = get_or_create_service_day(session, venue=venue, business_date=target_date)
    session.commit()
    assert second.id == first.id
    assert session.query(ServiceDay).filter_by(venue_id=venue.id, business_date=target_date).count() == 1


# --- open_service_day ----------------------------------------------------


def test_open_service_day_transitions_and_audits(session):
    owner, venue = _owner_and_venue(session)
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()

    opened = open_service_day(session, service_day=service_day, venue=venue, actor=owner)
    assert opened.status == ServiceDayStatus.open
    assert opened.opened_at is not None

    events = session.query(AuditEvent).filter_by(action="service_day.opened").all()
    assert len(events) == 1


def test_open_service_day_is_idempotent_no_duplicate_audit_event(session):
    owner, venue = _owner_and_venue(session)
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()

    open_service_day(session, service_day=service_day, venue=venue, actor=owner)
    open_service_day(session, service_day=service_day, venue=venue, actor=owner)

    events = session.query(AuditEvent).filter_by(action="service_day.opened").all()
    assert len(events) == 1


def test_open_service_day_refuses_to_reopen_a_closed_day(session):
    owner, venue = _owner_and_venue(session)
    service_day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    service_day.status = ServiceDayStatus.closed
    session.add(service_day)
    session.commit()

    with pytest.raises(CannotOpenClosedServiceDay):
        open_service_day(session, service_day=service_day, venue=venue, actor=owner)
