from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.handover import (
    CloseServiceDayRequest,
    HandoverOut,
    ReopenServiceDayRequest,
    SetHandoverItemIncludedRequest,
)
from app.core.database import get_session
from app.models.handover import HandoverItem
from app.models.membership import Membership
from app.models.service_day import ServiceDay
from app.models.user import User
from app.models.venue import Venue
from app.services.handover_service import (
    ServiceDayNotClosed,
    ServiceDayNotOpen,
    close_service_day,
    get_handover_for_service_day,
    reopen_service_day,
    set_handover_item_included,
)

router = APIRouter(tags=["handover"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_service_day_or_404(session: Session, venue_id: uuid.UUID, business_date: date) -> ServiceDay:
    service_day = session.query(ServiceDay).filter_by(venue_id=venue_id, business_date=business_date).one_or_none()
    if service_day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service day not found")
    return service_day


def _get_handover_item_or_404(session: Session, venue_id: uuid.UUID, item_id: uuid.UUID) -> HandoverItem:
    item = (
        session.query(HandoverItem)
        .join(HandoverItem.handover)
        .filter(HandoverItem.id == item_id, HandoverItem.handover.has(venue_id=venue_id))
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover item not found")
    return item


@router.post(
    "/venues/{venue_id}/service-days/{business_date}/close", response_model=HandoverOut
)
def close_service_day_route(
    venue_id: uuid.UUID,
    business_date: date,
    body: CloseServiceDayRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> HandoverOut:
    venue = _get_venue_or_404(session, venue_id)
    service_day = _get_service_day_or_404(session, venue_id, business_date)
    try:
        return close_service_day(session, venue=venue, actor=current_user, service_day=service_day, note=body.note)
    except ServiceDayNotOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/venues/{venue_id}/service-days/{business_date}/reopen", response_model=None
)
def reopen_service_day_route(
    venue_id: uuid.UUID,
    business_date: date,
    body: ReopenServiceDayRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> dict:
    venue = _get_venue_or_404(session, venue_id)
    service_day = _get_service_day_or_404(session, venue_id, business_date)
    try:
        reopen_service_day(session, venue=venue, actor=current_user, service_day=service_day, reason=body.reason)
    except ServiceDayNotClosed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"status": service_day.status.value}


@router.get(
    "/venues/{venue_id}/service-days/{business_date}/handover", response_model=HandoverOut
)
def get_handover_route(
    venue_id: uuid.UUID,
    business_date: date,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> HandoverOut:
    service_day = _get_service_day_or_404(session, venue_id, business_date)
    handover = get_handover_for_service_day(session, service_day_id=service_day.id)
    if handover is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This service day has no handover yet")
    return handover


@router.patch(
    "/venues/{venue_id}/handover-items/{item_id}/included", response_model=HandoverOut
)
def set_handover_item_included_route(
    venue_id: uuid.UUID,
    item_id: uuid.UUID,
    body: SetHandoverItemIncludedRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> HandoverOut:
    venue = _get_venue_or_404(session, venue_id)
    item = _get_handover_item_or_404(session, venue_id, item_id)
    set_handover_item_included(session, venue=venue, actor=current_user, handover_item=item, included=body.included)
    session.refresh(item.handover)
    return item.handover
