from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.audit import AuditEvent
from app.models.roster import Shift, ShiftStatus, StaffLink, StaffResponse, StaffResponseStatus
from app.models.service_day import ServiceDay, ServiceDayStatus
from app.models.user import User
from app.services.onboarding_service import create_organisation_with_venue
from app.services.roster_service import (
    CannotPublishCancelledShift,
    CopyWeekConflict,
    InvalidShiftWindow,
    InvalidStaffLink,
    OverlappingShift,
    ShiftNotRespondable,
    cancel_shift,
    compute_coverage_warnings,
    copy_week,
    create_shift,
    publish_shift,
    publish_week,
    respond_to_shift_as_staff,
    respond_to_shift_via_link,
    resolve_staff_link,
)
from app.services import email_service
from app.services.staffing_service import create_coverage_rule, create_staff, create_station

SYDNEY = ZoneInfo("Australia/Sydney")


@pytest.fixture(autouse=True)
def _reset_email_sender():
    """Every test gets the real default stub sender unless it explicitly
    monkeypatches email_service.EMAIL_SENDER — reset afterwards so tests
    never leak a fake sender into each other, same pattern as
    test_supplier_order_service.py's own EMAIL_PROVIDER fixture."""
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


def _dt(y, m, d, h, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=SYDNEY)


def _owner_and_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


# --- create_shift ----------------------------------------------------------


def test_create_shift_creates_pending_staff_response(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    assert shift.status == ShiftStatus.draft
    response = session.query(StaffResponse).filter_by(shift_id=shift.id).one()
    assert response.status == StaffResponseStatus.pending
    event = session.query(AuditEvent).filter_by(action="shift.created").one()
    assert event.entity_id == str(shift.id)


def test_create_shift_lazily_creates_service_day_still_planned(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 10, 9), end_at=_dt(2026, 6, 10, 17),
    )

    service_day = session.get(ServiceDay, shift.service_day_id)
    assert service_day.business_date == date(2026, 6, 10)
    # Creating a future Shift is "first referenced", not an operational
    # write — the ServiceDay stays planned until Epic 3/4 (or "Start day").
    assert service_day.status == ServiceDayStatus.planned


def test_create_shift_rejects_overlap_across_different_stations(session):
    owner, venue = _owner_and_venue(session)
    grill = create_station(session, venue=venue, actor=owner, name="Grill")
    salad = create_station(session, venue=venue, actor=owner, name="Salad")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    create_shift(
        session, venue=venue, actor=owner, station=grill, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    with pytest.raises(OverlappingShift):
        create_shift(
            session, venue=venue, actor=owner, station=salad, staff=staff,
            start_at=_dt(2026, 6, 1, 16), end_at=_dt(2026, 6, 1, 20),
        )


def test_create_shift_allows_back_to_back_shifts(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    second = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 21),
    )
    assert second.id is not None


def test_create_shift_rejects_naive_datetime(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    with pytest.raises(InvalidShiftWindow):
        create_shift(
            session, venue=venue, actor=owner, station=station, staff=staff,
            start_at=datetime(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
        )


def test_create_shift_rejects_end_before_start(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")

    with pytest.raises(InvalidShiftWindow):
        create_shift(
            session, venue=venue, actor=owner, station=station, staff=staff,
            start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 9),
        )


# --- cancel_shift ------------------------------------------------------


def test_cancel_shift_is_idempotent_and_revokes_links(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    publish_shift(session, venue=venue, actor=owner, shift=shift)
    link = session.query(StaffLink).filter_by(shift_id=shift.id).one()
    assert link.revoked_at is None

    cancel_shift(session, venue=venue, actor=owner, shift=shift)
    session.refresh(link)
    assert shift.status == ShiftStatus.cancelled
    assert link.revoked_at is not None

    # idempotent — no duplicate AuditEvent
    cancel_shift(session, venue=venue, actor=owner, shift=shift)
    events = session.query(AuditEvent).filter_by(action="shift.cancelled").all()
    assert len(events) == 1


# --- publish_shift / publish_week ---------------------------------------


def test_publish_shift_issues_link_and_queues_notification(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    result = publish_shift(session, venue=venue, actor=owner, shift=shift)

    assert result.shift.status == ShiftStatus.published
    assert result.staff_link_raw_token is not None
    link = session.query(StaffLink).filter_by(shift_id=shift.id, staff_id=staff.id).one()
    assert link.expires_at > datetime.now(timezone.utc)
    assert session.query(AuditEvent).filter_by(action="shift.published").count() == 1
    assert session.query(AuditEvent).filter_by(action="roster.notification_queued").count() == 1


def test_publish_shift_emails_staff_with_contact_email(session):
    """Epic 10 — a Staff member with no login at all still gets a real
    (stubbed) email, using their own contact_email."""
    sent = _capture_sent_emails()
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(
        session, venue=venue, actor=owner, name="Alex", contact_email="alex@example.com",
    )
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    publish_shift(session, venue=venue, actor=owner, shift=shift)

    assert [m.to for m in sent] == ["alex@example.com"]
    event = session.query(AuditEvent).filter_by(action="roster.notification_queued").one()
    assert event.after_data["sent"] is True
    assert event.after_data["message_id"] == "test-message-id"


def test_publish_shift_emails_staff_with_login_at_their_user_email(session):
    """A Staff member WITH a login is reached at their User.email, not a
    separate contact_email field — even if one happens to be set, the
    login identity wins (it's the address they actually use)."""
    sent = _capture_sent_emails()
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    linked_user = User(email="alex-login@example.com")
    session.add(linked_user)
    session.commit()
    staff = create_staff(
        session, venue=venue, actor=owner, name="Alex", user_id=linked_user.id,
        contact_email="alex-fallback@example.com",
    )
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    publish_shift(session, venue=venue, actor=owner, shift=shift)

    assert [m.to for m in sent] == ["alex-login@example.com"]


def test_publish_shift_with_no_delivery_address_records_not_sent(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")  # no user_id, no contact_email
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    publish_shift(session, venue=venue, actor=owner, shift=shift)

    assert sent == []
    event = session.query(AuditEvent).filter_by(action="roster.notification_queued").one()
    assert event.after_data["sent"] is False
    assert event.after_data["message_id"] is None


def test_cancel_shift_emails_staff_only_if_it_had_been_published(session):
    sent = _capture_sent_emails()
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(
        session, venue=venue, actor=owner, name="Alex", contact_email="alex@example.com",
    )
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )

    # Cancelling a still-draft shift: staff was never told, so no email.
    cancel_shift(session, venue=venue, actor=owner, shift=shift)
    assert sent == []
    assert session.query(AuditEvent).filter_by(action="roster.notification_queued").count() == 0

    # Publish a fresh shift, then cancel it — NOW it notifies.
    shift2 = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 2, 9), end_at=_dt(2026, 6, 2, 17),
    )
    publish_shift(session, venue=venue, actor=owner, shift=shift2)
    sent.clear()

    cancel_shift(session, venue=venue, actor=owner, shift=shift2)

    assert [m.to for m in sent] == ["alex@example.com"]
    notification_events = (
        session.query(AuditEvent).filter_by(action="roster.notification_queued", entity_id=str(staff.id)).all()
    )
    cancelled_events = [e for e in notification_events if e.after_data["reason"] == "shift_cancelled"]
    assert len(cancelled_events) == 1
    assert cancelled_events[0].after_data["sent"] is True


def test_publish_shift_is_idempotent_no_duplicate_link(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    publish_shift(session, venue=venue, actor=owner, shift=shift)
    second = publish_shift(session, venue=venue, actor=owner, shift=shift)

    assert second.staff_link_raw_token is None
    assert session.query(StaffLink).filter_by(shift_id=shift.id).count() == 1


def test_cannot_publish_cancelled_shift(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    cancel_shift(session, venue=venue, actor=owner, shift=shift)

    with pytest.raises(CannotPublishCancelledShift):
        publish_shift(session, venue=venue, actor=owner, shift=shift)


def test_publish_week_only_publishes_drafts_in_that_week(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    in_week = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    next_week = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 9, 9), end_at=_dt(2026, 6, 9, 17),
    )

    results = publish_week(session, venue=venue, actor=owner, week_start=date(2026, 6, 1))

    assert [r.shift.id for r in results] == [in_week.id]
    session.refresh(next_week)
    assert next_week.status == ShiftStatus.draft


# --- copy_week -----------------------------------------------------------


def test_copy_week_duplicates_as_draft_preserving_local_time(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    original = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 18), end_at=_dt(2026, 6, 2, 1),  # overnight, crosses midnight
    )
    publish_shift(session, venue=venue, actor=owner, shift=original)

    copied = copy_week(
        session, venue=venue, actor=owner,
        source_week_start=date(2026, 6, 1), target_week_start=date(2026, 6, 8),
    )

    assert len(copied) == 1
    new_shift = copied[0]
    assert new_shift.status == ShiftStatus.draft  # always draft, even though source was published
    assert new_shift.start_at.astimezone(SYDNEY).time() == time(18, 0)
    assert new_shift.start_at.astimezone(SYDNEY).date() == date(2026, 6, 8)
    assert new_shift.end_at.astimezone(SYDNEY).date() == date(2026, 6, 9)  # still crosses midnight
    new_response = session.query(StaffResponse).filter_by(shift_id=new_shift.id).one()
    assert new_response.status == StaffResponseStatus.pending

    new_service_day = session.get(ServiceDay, new_shift.service_day_id)
    assert new_service_day.business_date == date(2026, 6, 8)


def test_copy_week_ignores_cancelled_shifts(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    cancel_shift(session, venue=venue, actor=owner, shift=shift)

    copied = copy_week(
        session, venue=venue, actor=owner,
        source_week_start=date(2026, 6, 1), target_week_start=date(2026, 6, 8),
    )
    assert copied == []


def test_copy_week_conflict_leaves_nothing_persisted(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    # Already something in the TARGET week that will conflict with the copy.
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 8, 12), end_at=_dt(2026, 6, 8, 20),
    )

    shifts_before = session.query(Shift).count()
    with pytest.raises(CopyWeekConflict):
        copy_week(
            session, venue=venue, actor=owner,
            source_week_start=date(2026, 6, 1), target_week_start=date(2026, 6, 8),
        )
    assert session.query(Shift).count() == shifts_before


# --- Staff responses -------------------------------------------------------


def test_staff_response_independent_of_shift_cancellation(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    user = User(email="alex@example.com")
    session.add(user)
    session.commit()
    staff = create_staff(session, venue=venue, actor=owner, name="Alex", user_id=user.id)
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    publish_shift(session, venue=venue, actor=owner, shift=shift)

    respond_to_shift_as_staff(
        session, venue=venue, shift=shift, actor=user, response_status=StaffResponseStatus.confirmed
    )
    response = session.query(StaffResponse).filter_by(shift_id=shift.id).one()
    assert response.status == StaffResponseStatus.confirmed
    assert response.responded_via == "login"

    cancel_shift(session, venue=venue, actor=owner, shift=shift)
    session.refresh(response)
    assert shift.status == ShiftStatus.cancelled
    assert response.status == StaffResponseStatus.confirmed  # untouched by the cancellation


def test_cannot_respond_to_a_cancelled_shift(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    user = User(email="alex@example.com")
    session.add(user)
    session.commit()
    staff = create_staff(session, venue=venue, actor=owner, name="Alex", user_id=user.id)
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    cancel_shift(session, venue=venue, actor=owner, shift=shift)

    with pytest.raises(ShiftNotRespondable):
        respond_to_shift_as_staff(
            session, venue=venue, shift=shift, actor=user, response_status=StaffResponseStatus.confirmed
        )


def test_respond_via_staff_link(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    result = publish_shift(session, venue=venue, actor=owner, shift=shift)

    response = respond_to_shift_via_link(
        session, raw_token=result.staff_link_raw_token, response_status=StaffResponseStatus.declined
    )
    assert response.status == StaffResponseStatus.declined
    assert response.responded_via == "staff_link"


def test_staff_link_invalid_token_raises(session):
    with pytest.raises(InvalidStaffLink):
        resolve_staff_link(session, raw_token="not-a-real-token")


def test_staff_link_invalidated_when_shift_cancelled(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 9), end_at=_dt(2026, 6, 1, 17),
    )
    result = publish_shift(session, venue=venue, actor=owner, shift=shift)
    cancel_shift(session, venue=venue, actor=owner, shift=shift)

    with pytest.raises(InvalidStaffLink):
        respond_to_shift_via_link(
            session, raw_token=result.staff_link_raw_token, response_status=StaffResponseStatus.confirmed
        )


# --- Coverage warnings -----------------------------------------------------


def test_coverage_warning_fires_when_understaffed(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(17, 0), window_end=time(22, 0), minimum_staff=2,
    )
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 22),
    )

    warnings = compute_coverage_warnings(session, venue=venue, business_date=date(2026, 6, 1))
    assert len(warnings) == 1
    assert warnings[0].scheduled_staff == 1
    assert warnings[0].minimum_staff == 2


def test_coverage_warning_absent_when_minimum_met(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    alex = create_staff(session, venue=venue, actor=owner, name="Alex")
    sam = create_staff(session, venue=venue, actor=owner, name="Sam")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(17, 0), window_end=time(22, 0), minimum_staff=2,
    )
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=alex,
        start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 22),
    )
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=sam,
        start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 22),
    )

    warnings = compute_coverage_warnings(session, venue=venue, business_date=date(2026, 6, 1))
    assert warnings == []


def test_coverage_warning_ignores_shift_outside_the_window(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(17, 0), window_end=time(22, 0), minimum_staff=1,
    )
    # A short morning shift that never overlaps the dinner window shouldn't
    # count as "covering" it.
    create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 8), end_at=_dt(2026, 6, 1, 11),
    )

    warnings = compute_coverage_warnings(session, venue=venue, business_date=date(2026, 6, 1))
    assert len(warnings) == 1
    assert warnings[0].scheduled_staff == 0


def test_coverage_warning_ignores_cancelled_shifts(session):
    owner, venue = _owner_and_venue(session)
    station = create_station(session, venue=venue, actor=owner, name="Grill")
    staff = create_staff(session, venue=venue, actor=owner, name="Alex")
    create_coverage_rule(
        session, venue=venue, actor=owner, station=station,
        day_of_week=0, window_start=time(17, 0), window_end=time(22, 0), minimum_staff=1,
    )
    shift = create_shift(
        session, venue=venue, actor=owner, station=station, staff=staff,
        start_at=_dt(2026, 6, 1, 17), end_at=_dt(2026, 6, 1, 22),
    )
    cancel_shift(session, venue=venue, actor=owner, shift=shift)

    warnings = compute_coverage_warnings(session, venue=venue, business_date=date(2026, 6, 1))
    assert len(warnings) == 1
    assert warnings[0].scheduled_staff == 0
