from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.capture import (
    CaptureOut,
    ConfirmCaptureRequest,
    ConfirmCaptureResult,
    CreateCaptureRequest,
    RejectCaptureRequest,
)
from app.core.database import get_session
from app.models.capture import Capture, CaptureType
from app.models.membership import Membership
from app.models.user import User
from app.models.venue import Venue
from app.services.capture_service import (
    CaptureAlreadyDecided,
    MissingConfirmationDetails,
    UnknownMatchedEntity,
    UnresolvedCapture,
    confirm_capture,
    create_capture,
    reject_capture,
)
from app.services.service_day_service import ServiceDayIsClosed

router = APIRouter(tags=["quick-capture"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_capture_or_404(session: Session, venue_id: uuid.UUID, capture_id: uuid.UUID) -> Capture:
    capture = session.query(Capture).filter_by(id=capture_id, venue_id=venue_id).one_or_none()
    if capture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture not found")
    return capture


@router.post("/venues/{venue_id}/captures", response_model=CaptureOut, status_code=status.HTTP_201_CREATED)
def create_capture_route(
    venue_id: uuid.UUID,
    body: CreateCaptureRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> CaptureOut:
    """No mic/camera affordance here or anywhere else in Quick Capture —
    raw_text is free text the chef typed, full stop (locked AC)."""
    venue = _get_venue_or_404(session, venue_id)
    try:
        return create_capture(
            session, venue=venue, actor=current_user, raw_text=body.raw_text,
            business_date=body.business_date, added_after_close=body.added_after_close,
        )
    except ServiceDayIsClosed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/venues/{venue_id}/captures", response_model=list[CaptureOut])
def list_captures(
    venue_id: uuid.UUID,
    capture_status: str | None = None,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[CaptureOut]:
    query = session.query(Capture).filter_by(venue_id=venue_id)
    if capture_status is not None:
        query = query.filter_by(status=capture_status)
    return query.order_by(Capture.created_at.desc()).all()


@router.get("/venues/{venue_id}/captures/{capture_id}", response_model=CaptureOut)
def get_capture(
    venue_id: uuid.UUID,
    capture_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> CaptureOut:
    return _get_capture_or_404(session, venue_id, capture_id)


@router.post("/venues/{venue_id}/captures/{capture_id}/confirm", response_model=ConfirmCaptureResult)
def confirm_capture_route(
    venue_id: uuid.UUID,
    capture_id: uuid.UUID,
    body: ConfirmCaptureRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ConfirmCaptureResult:
    venue = _get_venue_or_404(session, venue_id)
    capture = _get_capture_or_404(session, venue_id, capture_id)
    try:
        capture, result = confirm_capture(
            session, venue=venue, actor=current_user, capture=capture,
            entity_type=body.entity_type, entity_id=body.entity_id,
            quantity=body.quantity, unit=body.unit,
            supplier_id=body.supplier_id, required_delivery_date=body.required_delivery_date,
            order_cycle=body.order_cycle,
            availability_status=body.availability_status, quantity_remaining=body.quantity_remaining,
            priority=body.priority, photos=body.photos,
        )
    except (CaptureAlreadyDecided, ServiceDayIsClosed) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (UnresolvedCapture, UnknownMatchedEntity, MissingConfirmationDetails) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

    result_type = {
        CaptureType.eighty_six: "menu_availability_event",
        CaptureType.equipment_issue: "equipment_issue",
        CaptureType.restock: "purchase_order",
    }[capture.capture_type]
    return ConfirmCaptureResult(capture=capture, result_type=result_type, result_id=result.id)


@router.post("/venues/{venue_id}/captures/{capture_id}/reject", response_model=CaptureOut)
def reject_capture_route(
    venue_id: uuid.UUID,
    capture_id: uuid.UUID,
    body: RejectCaptureRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> CaptureOut:
    venue = _get_venue_or_404(session, venue_id)
    capture = _get_capture_or_404(session, venue_id, capture_id)
    try:
        return reject_capture(session, venue=venue, actor=current_user, capture=capture, reason=body.reason)
    except (CaptureAlreadyDecided, ServiceDayIsClosed) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
