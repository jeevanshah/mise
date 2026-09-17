from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.attendance import AttendanceSource, AttendanceStatus
from app.models.user import User
from app.services.attendance_service import (
    DuplicateStaffCheckIn,
    get_current_status,
    list_attendance_history,
    log_attendance_as_chef,
    log_attendance_via_link,
)
from app.services.onboarding_service import create_organisation_with_venue
from app.services.roster_service import create_shift, publish_shift
from app.services.staffing_service import create_staff, create_station

SYDNEY = ZoneInfo("Australia/Sydney")


def _dt(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=SYDNEY)


def _owner_venue_shift(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    return owner, venue, shift


def test_no_event_means_expected(session):
    owner, venue, shift = _owner_venue_shift(session)
    assert get_current_status(session, shift=shift) is None


def test_chef_logs_attendance(session):
    owner, venue, shift = _owner_venue_shift(session)
    event = log_attendance_as_chef(
        session, venue=venue, actor=owner, shift=shift, status=AttendanceStatus.present
    )
    assert event.source == AttendanceSource.chef
    assert event.actor_user_id == owner.id
    assert get_current_status(session, shift=shift) == AttendanceStatus.present


def test_later_chef_event_overrides_displayed_state_but_keeps_history(session):
    owner, venue, shift = _owner_venue_shift(session)
    result = publish_shift(session, venue=venue, actor=owner, shift=shift)

    log_attendance_via_link(
        session, raw_token=result.staff_link_raw_token, status=AttendanceStatus.present
    )
    assert get_current_status(session, shift=shift) == AttendanceStatus.present

    log_attendance_as_chef(session, venue=venue, actor=owner, shift=shift, status=AttendanceStatus.late)
    assert get_current_status(session, shift=shift) == AttendanceStatus.late

    history = list_attendance_history(session, shift=shift)
    assert [e.source for e in history] == [AttendanceSource.staff_link, AttendanceSource.chef]
    assert [e.status for e in history] == [AttendanceStatus.present, AttendanceStatus.late]


def test_staff_can_only_check_in_once_via_link(session):
    owner, venue, shift = _owner_venue_shift(session)
    result = publish_shift(session, venue=venue, actor=owner, shift=shift)

    log_attendance_via_link(session, raw_token=result.staff_link_raw_token, status=AttendanceStatus.present)

    with pytest.raises(DuplicateStaffCheckIn):
        log_attendance_via_link(session, raw_token=result.staff_link_raw_token, status=AttendanceStatus.late)


def test_chef_can_log_multiple_corrections(session):
    owner, venue, shift = _owner_venue_shift(session)
    log_attendance_as_chef(session, venue=venue, actor=owner, shift=shift, status=AttendanceStatus.absent)
    log_attendance_as_chef(session, venue=venue, actor=owner, shift=shift, status=AttendanceStatus.present)

    history = list_attendance_history(session, shift=shift)
    assert len(history) == 2
    assert get_current_status(session, shift=shift) == AttendanceStatus.present


def test_no_location_or_gps_field_exists():
    from app.models.attendance import AttendanceEvent

    columns = {c.name for c in AttendanceEvent.__table__.columns}
    assert not any(
        term in col.lower() for col in columns for term in ("lat", "lon", "gps", "location", "device")
    )
