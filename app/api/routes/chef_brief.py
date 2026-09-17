from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_membership
from app.api.schemas.chef_brief import ChefBriefOut
from app.core.database import get_session
from app.models.membership import Membership
from app.models.user import User
from app.models.venue import Venue
from app.services.chef_brief_service import get_chef_brief

router = APIRouter(tags=["chef-brief"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.get("/venues/{venue_id}/chef-brief", response_model=ChefBriefOut)
def get_chef_brief_route(
    venue_id: uuid.UUID,
    business_date: date | None = None,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ChefBriefOut:
    """Default landing view (locked AC): defaults to the current
    ServiceDay's Brief when business_date is omitted. Any Membership can
    open it — the Brief is kitchen-floor-visible, not a management-only
    view — and every open is logged as its own AuditEvent (see
    chef_brief_service's docstring on why that's unconditional, not
    deduped)."""
    venue = _get_venue_or_404(session, venue_id)
    return get_chef_brief(session, venue=venue, actor=current_user, business_date=business_date)
