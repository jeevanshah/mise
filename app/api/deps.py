"""
FastAPI dependencies for auth and Membership-based permission enforcement
(Epic 1 step 4).

Route handlers that need a Venue-scoped role check take a `venue_id` path
parameter and depend on `require_membership(...)`, e.g.:

    @router.post("/venues/{venue_id}/stations")
    def create_station(
        venue_id: uuid.UUID,
        membership: Membership = Depends(require_membership(
            MembershipRole.owner, MembershipRole.head_chef,
        )),
        session: Session = Depends(get_session),
    ):
        ...

`require_membership` re-queries the DB on every call — no role/venue data
is cached in the access token — so a Membership removed or changed takes
effect on the very next request.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.services.auth_service import InvalidAccessToken, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_membership(*allowed_roles: MembershipRole):
    """Dependency factory. With no roles passed, any Membership on the
    path's `venue_id` is sufficient (authenticated + belongs to this venue);
    pass specific roles to also enforce role-based access."""

    def _dependency(
        venue_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: Session = Depends(get_session),
    ) -> Membership:
        membership = (
            session.query(Membership)
            .filter_by(user_id=current_user.id, venue_id=venue_id)
            .one_or_none()
        )
        if membership is None:
            # Same 403 whether the venue doesn't exist, the user has no
            # Membership there, or it belongs to someone else — never
            # reveal which, that's an enumeration leak across tenants.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this venue",
            )
        if allowed_roles and membership.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this action",
            )
        return membership

    return _dependency
