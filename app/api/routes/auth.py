from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas.auth import (
    MagicLinkRequest,
    MagicLinkRequestResponse,
    MagicLinkVerifyRequest,
    MeResponse,
    TokenResponse,
)
from app.core.config import settings
from app.core.database import get_session
from app.models.membership import Membership
from app.models.user import User
from app.services.auth_service import (
    InvalidOrExpiredToken,
    create_access_token,
    issue_magic_link,
    verify_magic_link,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-link", response_model=MagicLinkRequestResponse)
def request_magic_link(
    body: MagicLinkRequest, session: Session = Depends(get_session)
) -> MagicLinkRequestResponse:
    """
    Find-or-create the User by email and issue a single-use login link.

    No email provider exists yet (Epic 10). Until then: outside production,
    the raw token is returned directly in the response so the flow is fully
    testable end-to-end; in production this endpoint currently has nowhere
    to deliver the token, so it responds without one — wiring it to an
    actual email send is Epic 10's job, not a step-4 shortcut to skip.
    """
    issued = issue_magic_link(session, email=body.email)

    if settings.environment == "production":
        return MagicLinkRequestResponse(
            detail="If that email is registered, a login link has been sent."
        )
    return MagicLinkRequestResponse(
        detail="Dev mode: no email sent — use dev_token to verify.",
        dev_token=issued.raw_token,
    )


@router.post("/verify", response_model=TokenResponse)
def verify_magic_link_and_issue_token(
    body: MagicLinkVerifyRequest, session: Session = Depends(get_session)
) -> TokenResponse:
    try:
        user = verify_magic_link(session, raw_token=body.token)
    except InvalidOrExpiredToken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    access_token = create_access_token(user.id)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=MeResponse)
def read_current_user(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MeResponse:
    memberships = session.query(Membership).filter_by(user_id=current_user.id).all()
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        memberships=memberships,
    )
