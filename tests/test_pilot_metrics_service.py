from datetime import date

import pytest

from app.models.user import User
from app.services.onboarding_service import create_organisation_with_venue
from app.services.pilot_metrics_service import (
    INCIDENT_ACTION,
    MINUTES_SAVED_ACTION,
    PILOT_DECISION_ACTION,
    InvalidIncidentType,
    get_pilot_metrics,
    log_incident,
    record_minutes_saved,
    record_pilot_decision,
)


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_record_minutes_saved_writes_an_event(session):
    owner, venue = _owner_venue(session)

    event = record_minutes_saved(
        session, venue=venue, actor=owner, week_start=date(2026, 6, 1), minutes_saved=45,
    )

    assert event.action == MINUTES_SAVED_ACTION
    assert event.after_data == {"week_start": "2026-06-01", "minutes_saved": 45}


def test_log_incident_is_tagged_to_the_service_day(session):
    owner, venue = _owner_venue(session)

    event = log_incident(
        session, venue=venue, actor=owner, business_date=date(2026, 6, 1),
        incident_type="missed_order", description="Supplier never received the Friday order",
    )

    assert event.action == INCIDENT_ACTION
    assert event.entity_type == "service_day"
    assert event.after_data["incident_type"] == "missed_order"


def test_log_incident_rejects_unknown_incident_type(session):
    owner, venue = _owner_venue(session)

    with pytest.raises(InvalidIncidentType):
        log_incident(
            session, venue=venue, actor=owner, business_date=date(2026, 6, 1),
            incident_type="something_else", description="n/a",
        )


def test_record_pilot_decision_writes_an_event(session):
    owner, venue = _owner_venue(session)

    event = record_pilot_decision(
        session, venue=venue, actor=owner, will_pay_at_proposed_price=True, notes="Ready to sign",
    )

    assert event.action == PILOT_DECISION_ACTION
    assert event.after_data == {"will_pay_at_proposed_price": True, "notes": "Ready to sign"}


def test_get_pilot_metrics_returns_all_three_kinds_oldest_first(session):
    owner, venue = _owner_venue(session)
    record_minutes_saved(session, venue=venue, actor=owner, week_start=date(2026, 6, 1), minutes_saved=30)
    log_incident(
        session, venue=venue, actor=owner, business_date=date(2026, 6, 1),
        incident_type="handover_failure", description="Handover note never got read",
    )
    record_pilot_decision(session, venue=venue, actor=owner, will_pay_at_proposed_price=False)

    events = get_pilot_metrics(session, venue=venue)

    assert [e.action for e in events] == [MINUTES_SAVED_ACTION, INCIDENT_ACTION, PILOT_DECISION_ACTION]
