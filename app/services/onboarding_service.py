"""
Epic 1 step 5 — Org/Venue onboarding endpoints (service layer).

Covers the two onboarding ACs from the locked spec:
  - "Org owner signs up via magic link, creates one Organisation + one Venue
    with a timezone and business_day_boundary (default 04:00, editable)."
  - "Owner invites Users by email; each gets a Membership (role × Venue)."

Every mutation here goes through audited_transaction (Epic 1 step 3), per
the rev-3 correction that moved audit logging into the foundation instead
of bolting it on later. Organisation/Venue creation is the one case where
the entities being audited don't exist yet when we'd normally open the
transaction, so this module flushes them first (assigns their ids, but
does not commit) and only then opens the audited block — the block's
single commit() at the end still covers everything, org/venue included,
so the whole signup remains one atomic unit: fail anywhere and nothing
persists, not even the "successfully" flushed rows.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy.orm import Session

from app.models.membership import Membership, MembershipRole
from app.models.organisation import Organisation
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction
from app.services.user_service import find_or_create_user


class MembershipAlreadyExists(Exception):
    """Raised when inviting an email that already has a Membership at this
    venue — inviting again would silently change their role via a route
    named "invite", which is surprising; use a dedicated role-change
    operation for that instead (not needed until Epic 1's ACs ask for it)."""


def create_organisation_with_venue(
    session: Session,
    *,
    owner: User,
    organisation_name: str,
    venue_name: str,
    timezone: str | None = None,
    business_day_boundary: time | None = None,
) -> tuple[Organisation, Venue, Membership]:
    """The "sign up" flow: the authenticated User becomes the owner
    Membership on a brand-new Organisation + Venue. There is deliberately
    no separate registration step — the User already exists from the
    magic-link login (Epic 1 step 4); this is the first business action
    they take with it."""
    organisation = Organisation(name=organisation_name)
    session.add(organisation)
    session.flush()

    venue_kwargs: dict = {"organisation_id": organisation.id, "name": venue_name}
    if timezone is not None:
        venue_kwargs["timezone"] = timezone
    if business_day_boundary is not None:
        venue_kwargs["business_day_boundary"] = business_day_boundary
    venue = Venue(**venue_kwargs)
    session.add(venue)
    session.flush()

    with audited_transaction(
        session, organisation_id=organisation.id, venue_id=venue.id, actor_user_id=owner.id
    ) as audit:
        membership = Membership(user_id=owner.id, venue_id=venue.id, role=MembershipRole.owner)
        session.add(membership)
        session.flush()

        audit.record(
            action="organisation.created",
            entity_type="organisation",
            entity_id=organisation.id,
            after={"name": organisation.name},
        )
        audit.record(
            action="venue.created",
            entity_type="venue",
            entity_id=venue.id,
            after={
                "name": venue.name,
                "timezone": venue.timezone,
                "business_day_boundary": venue.business_day_boundary.isoformat(),
            },
        )
        audit.record(
            action="membership.created",
            entity_type="membership",
            entity_id=membership.id,
            after={"user_id": str(owner.id), "role": membership.role.value},
        )

    return organisation, venue, membership


def update_venue_settings(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    timezone: str | None = None,
    business_day_boundary: time | None = None,
) -> Venue:
    before = {
        "timezone": venue.timezone,
        "business_day_boundary": venue.business_day_boundary.isoformat(),
    }
    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=actor.id,
    ) as audit:
        if timezone is not None:
            venue.timezone = timezone
        if business_day_boundary is not None:
            venue.business_day_boundary = business_day_boundary
        session.add(venue)
        session.flush()

        audit.record(
            action="venue.updated",
            entity_type="venue",
            entity_id=venue.id,
            before=before,
            after={
                "timezone": venue.timezone,
                "business_day_boundary": venue.business_day_boundary.isoformat(),
            },
        )

    return venue


def invite_user_to_venue(
    session: Session,
    *,
    venue: Venue,
    inviter: User,
    invitee_email: str,
    role: MembershipRole,
) -> tuple[User, Membership]:
    """Find-or-create the invitee by email, then grant them a Membership.
    Raises MembershipAlreadyExists if they already have one at this venue —
    see that class's docstring for why this isn't silently treated as a
    role change."""
    invitee = find_or_create_user(session, email=invitee_email)

    existing = (
        session.query(Membership).filter_by(user_id=invitee.id, venue_id=venue.id).one_or_none()
    )
    if existing is not None:
        raise MembershipAlreadyExists(
            f"{invitee.email} already has a Membership at this venue"
        )

    with audited_transaction(
        session,
        organisation_id=venue.organisation_id,
        venue_id=venue.id,
        actor_user_id=inviter.id,
    ) as audit:
        membership = Membership(user_id=invitee.id, venue_id=venue.id, role=role)
        session.add(membership)
        session.flush()

        audit.record(
            action="membership.created",
            entity_type="membership",
            entity_id=membership.id,
            after={"user_id": str(invitee.id), "email": invitee.email, "role": role.value},
        )

    return invitee, membership
