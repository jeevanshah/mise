from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.service_days import ServiceDayOut, StartServiceDayRequest
from app.core.database import get_session
from app.models.membership import Membership
from app.models.user import User
from app.models.venue import Venue
from app.services.service_day_service import (
    CannotOpenClosedServiceDay,
    get_or_create_service_day,
    open_service_day,
    resolve_business_date,
)

router = APIRouter(tags=["service-days"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.get("/venues/{venue_id}/service-days/current", response_model=ServiceDayOut)
def get_current_service_day(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ServiceDayOut:
    """Lazily creates today's ServiceDay for this venue (per its timezone +
    business_day_boundary) if it doesn't exist yet. Any Membership can call
    this — it's a read from the caller's point of view even though it may
    create the row on first reference, exactly as the AC describes."""
    venue = _get_venue_or_404(session, venue_id)
    business_date = resolve_business_date(venue)
    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    session.commit()
    return service_day


@router.post("/venues/{venue_id}/service-days/start", response_model=ServiceDayOut)
def start_service_day(
    venue_id: uuid.UUID,
    body: StartServiceDayRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ServiceDayOut:
    """The explicit "Start day" action. Defaults to today's business_date
    (per the venue's own clock) when none is given. Idempotent and audited
    — see open_service_day."""
    venue = _get_venue_or_404(session, venue_id)
    business_date = body.business_date or resolve_business_date(venue)
    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    try:
        return open_service_day(session, service_day=service_day, venue=venue, actor=current_user)
    except CannotOpenClosedServiceDay as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
