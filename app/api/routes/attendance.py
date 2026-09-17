from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.attendance import (
    AttendanceEventCreateRequest,
    AttendanceEventOut,
    CurrentAttendanceOut,
)
from app.core.database import get_session
from app.models.membership import Membership
from app.models.roster import Shift
from app.models.user import User
from app.models.venue import Venue
from app.services.attendance_service import (
    DuplicateStaffCheckIn,
    get_current_status,
    list_attendance_history,
    log_attendance_as_chef,
    log_attendance_via_link,
)
from app.services.roster_service import InvalidStaffLink

router = APIRouter(tags=["attendance"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_shift_or_404(session: Session, venue_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
    shift = session.query(Shift).filter_by(id=shift_id, venue_id=venue_id).one_or_none()
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return shift


@router.post(
    "/venues/{venue_id}/shifts/{shift_id}/attendance-events",
    response_model=AttendanceEventOut,
    status_code=status.HTTP_201_CREATED,
)
def log_attendance_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    body: AttendanceEventCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> AttendanceEventOut:
    venue = _get_venue_or_404(session, venue_id)
    shift = _get_shift_or_404(session, venue_id, shift_id)
    return log_attendance_as_chef(
        session, venue=venue, actor=current_user, shift=shift, status=body.status, note=body.note
    )


@router.get(
    "/venues/{venue_id}/shifts/{shift_id}/attendance-events",
    response_model=list[AttendanceEventOut],
)
def list_attendance_events_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[AttendanceEventOut]:
    shift = _get_shift_or_404(session, venue_id, shift_id)
    return list_attendance_history(session, shift=shift)


@router.get(
    "/venues/{venue_id}/shifts/{shift_id}/attendance",
    response_model=CurrentAttendanceOut,
)
def get_current_attendance_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> CurrentAttendanceOut:
    shift = _get_shift_or_404(session, venue_id, shift_id)
    return CurrentAttendanceOut(shift_id=shift.id, status=get_current_status(session, shift=shift))


@router.post(
    "/staff-links/{token}/attendance-events",
    response_model=AttendanceEventOut,
    status_code=status.HTTP_201_CREATED,
)
def check_in_via_link_route(
    token: str, body: AttendanceEventCreateRequest, session: Session = Depends(get_session)
) -> AttendanceEventOut:
    try:
        return log_attendance_via_link(session, raw_token=token, status=body.status, note=body.note)
    except InvalidStaffLink as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DuplicateStaffCheckIn as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
