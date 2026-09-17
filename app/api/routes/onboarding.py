from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_membership
from app.api.schemas.onboarding import (
    InviteUserRequest,
    InviteUserResponse,
    OrganisationCreateRequest,
    OrganisationCreateResponse,
    VenueOut,
    VenueUpdateRequest,
)
from app.core.database import get_session
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.models.venue import Venue
from app.services.onboarding_service import (
    MembershipAlreadyExists,
    create_organisation_with_venue,
    invite_user_to_venue,
    update_venue_settings,
)

router = APIRouter(tags=["onboarding"])


@router.post("/organisations", response_model=OrganisationCreateResponse, status_code=status.HTTP_201_CREATED)
def create_organisation(
    body: OrganisationCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> OrganisationCreateResponse:
    """The "sign up" step: any authenticated User (i.e. anyone who has
    completed magic-link login) can create an Organisation + Venue and
    becomes its owner. There is no separate registration form — logging in
    for the first time and creating your first venue are the same journey."""
    organisation, venue, membership = create_organisation_with_venue(
        session,
        owner=current_user,
        organisation_name=body.organisation_name,
        venue_name=body.venue_name,
        timezone=body.timezone,
        business_day_boundary=body.business_day_boundary,
    )
    return OrganisationCreateResponse(organisation=organisation, venue=venue, membership=membership)


@router.get("/venues/{venue_id}", response_model=VenueOut)
def get_venue(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001 — any role
    session: Session = Depends(get_session),
) -> VenueOut:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — FK from Membership guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.patch("/venues/{venue_id}", response_model=VenueOut)
def update_venue(
    venue_id: uuid.UUID,
    body: VenueUpdateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(MembershipRole.owner)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> VenueOut:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return update_venue_settings(
        session,
        venue=venue,
        actor=current_user,
        timezone=body.timezone,
        business_day_boundary=body.business_day_boundary,
    )


@router.post("/venues/{venue_id}/invite", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED)
def invite_user(
    venue_id: uuid.UUID,
    body: InviteUserRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(MembershipRole.owner)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> InviteUserResponse:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")

    try:
        invitee, new_membership = invite_user_to_venue(
            session,
            venue=venue,
            inviter=current_user,
            invitee_email=body.email,
            role=body.role,
        )
    except MembershipAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person already has a Membership at this venue",
        )

    return InviteUserResponse(
        user_id=invitee.id, email=invitee.email, venue_id=venue_id, role=new_membership.role
    )
