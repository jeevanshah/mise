"""
Unit tests for app/services/onboarding_service.py.
"""

from datetime import time

import pytest

from app.models.audit import AuditEvent
from app.models.membership import Membership, MembershipRole
from app.models.organisation import Organisation
from app.models.user import User
from app.models.venue import Venue
from app.services.onboarding_service import (
    MembershipAlreadyExists,
    create_organisation_with_venue,
    invite_user_to_venue,
    update_venue_settings,
)


def _make_user(session, email="owner@example.com") -> User:
    user = User(email=email)
    session.add(user)
    session.commit()
    return user


def test_create_organisation_with_venue_creates_owner_membership(session):
    owner = _make_user(session)

    org, venue, membership = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )

    assert session.get(Organisation, org.id) is not None
    assert session.get(Venue, venue.id).organisation_id == org.id
    assert membership.user_id == owner.id
    assert membership.venue_id == venue.id
    assert membership.role == MembershipRole.owner


def test_create_organisation_defaults_timezone_and_boundary_when_not_given(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    assert venue.timezone == "Australia/Sydney"
    assert venue.business_day_boundary == time(4, 0)


def test_create_organisation_honours_explicit_timezone_and_boundary(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session,
        owner=owner,
        organisation_name="Test Co",
        venue_name="Test Diner",
        timezone="Australia/Perth",
        business_day_boundary=time(3, 30),
    )
    assert venue.timezone == "Australia/Perth"
    assert venue.business_day_boundary == time(3, 30)


def test_create_organisation_writes_audit_events_for_all_three_entities(session):
    owner = _make_user(session)
    org, venue, membership = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )

    actions = {e.action for e in session.query(AuditEvent).filter_by(venue_id=venue.id).all()}
    assert actions == {"organisation.created", "venue.created", "membership.created"}


def test_create_organisation_is_atomic_nothing_persists_if_membership_insert_fails(session):
    owner = _make_user(session)

    from unittest.mock import patch

    with patch(
        "app.services.onboarding_service.Membership",
        side_effect=RuntimeError("simulated failure"),
    ):
        with pytest.raises(RuntimeError):
            create_organisation_with_venue(
                session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
            )

    session.rollback()
    assert session.query(Organisation).filter_by(name="Test Co").count() == 0
    assert session.query(Venue).filter_by(name="Test Diner").count() == 0
    assert session.query(AuditEvent).count() == 0


def test_update_venue_settings_changes_fields_and_records_before_after(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )

    update_venue_settings(session, venue=venue, actor=owner, timezone="Australia/Perth")

    session.expire_all()
    refreshed = session.get(Venue, venue.id)
    assert refreshed.timezone == "Australia/Perth"

    event = (
        session.query(AuditEvent)
        .filter_by(entity_id=str(venue.id), action="venue.updated")
        .one()
    )
    assert event.before_data["timezone"] == "Australia/Sydney"
    assert event.after_data["timezone"] == "Australia/Perth"


def test_invite_user_to_venue_creates_new_user_and_membership(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )

    invitee, membership = invite_user_to_venue(
        session,
        venue=venue,
        inviter=owner,
        invitee_email="souschef@example.com",
        role=MembershipRole.sous_chef,
    )

    assert invitee.email == "souschef@example.com"
    assert membership.role == MembershipRole.sous_chef
    assert membership.venue_id == venue.id


def test_invite_user_to_venue_reuses_existing_user(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    existing_user = User(email="existing@example.com")
    session.add(existing_user)
    session.commit()

    invitee, _ = invite_user_to_venue(
        session, venue=venue, inviter=owner, invitee_email="Existing@Example.com",
        role=MembershipRole.head_chef,
    )

    assert invitee.id == existing_user.id
    assert session.query(User).filter_by(email="existing@example.com").count() == 1


def test_invite_user_to_venue_rejects_duplicate_membership(session):
    owner = _make_user(session)
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    invite_user_to_venue(
        session, venue=venue, inviter=owner, invitee_email="chef@example.com",
        role=MembershipRole.sous_chef,
    )

    with pytest.raises(MembershipAlreadyExists):
        invite_user_to_venue(
            session, venue=venue, inviter=owner, invitee_email="chef@example.com",
            role=MembershipRole.head_chef,
        )

    # role from the first invite must be untouched
    membership = (
        session.query(Membership)
        .join(User, Membership.user_id == User.id)
        .filter(User.email == "chef@example.com")
        .one()
    )
    assert membership.role == MembershipRole.sous_chef
