from datetime import time

import pytest

from app.models.audit import AuditEvent
from app.models.station import StationCoverageRule
from app.models.user import User
from app.services.onboarding_service import create_organisation_with_venue
from app.services.staffing_service import (
    DuplicateCoverageRule,
    DuplicateStaffSkill,
    InvalidCoverageWindow,
    add_staff_skill,
    create_coverage_rule,
    create_staff,
    create_station,
)


def _owner_and_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_create_station_writes_audit_event(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")

    assert station.venue_id == venue.id
    event = session.query(AuditEvent).filter_by(action="station.created").one()
    assert event.entity_id == str(station.id)


def test_create_staff_without_user_is_allowed(session):
    owner, venue = _owner_and_venue(session)
    staff = create_staff(session, venue=venue, actor=owner, name="Line Cook")
    assert staff.user_id is None


def test_create_staff_with_user_id_links_it(session):
    owner, venue = _owner_and_venue(session)
    other_user = User(email="linked@example.com")
    session.add(other_user)
    session.commit()

    staff = create_staff(session, venue=venue, actor=owner, name="Head Chef", user_id=other_user.id)
    assert staff.user_id == other_user.id


def test_add_staff_skill_creates_and_rejects_duplicate(session):
    owner, venue = _owner_and_venue(session)
    staff = create_staff(session, venue=venue, actor=owner, name="Line Cook")
    station = create_station(session, venue=venue, actor=owner, name="Grill")

    skill = add_staff_skill(session, venue=venue, actor=owner, staff=staff, station=station)
    assert skill.trained is True

    with pytest.raises(DuplicateStaffSkill):
        add_staff_skill(session, venue=venue, actor=owner, staff=staff, station=station)


def test_create_coverage_rule_rejects_backwards_window(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")

    with pytest.raises(InvalidCoverageWindow):
        create_coverage_rule(
            session, venue=venue, actor=owner, station=station,
            day_of_week=0, window_start=time(14, 0), window_end=time(10, 0),
        )


def test_create_coverage_rule_rejects_exact_duplicate(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(10, 0), window_end=time(14, 0), minimum_staff=2,
    )

    with pytest.raises(DuplicateCoverageRule):
        create_coverage_rule(
            session, venue=venue, actor=owner, station=station,
            day_of_week=0, window_start=time(10, 0), window_end=time(14, 0), minimum_staff=3,
        )

    assert session.query(StationCoverageRule).count() == 1
