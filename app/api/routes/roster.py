from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.roster import (
    CopyWeekRequest,
    CoverageWarningOut,
    PublishResultOut,
    PublishWeekRequest,
    ShiftCreateRequest,
    ShiftOut,
    StaffLinkShiftView,
    StaffRespondRequest,
)
from app.core.config import settings
from app.core.database import get_session
from app.models.membership import Membership
from app.models.roster import Shift, StaffResponseStatus
from app.models.service_day import ServiceDay
from app.models.staff import Staff
from app.models.station import Station
from app.models.user import User
from app.models.venue import Venue
from app.services.pdf_export_service import render_roster_pdf
from app.services.roster_service import (
    CannotPublishCancelledShift,
    CopyWeekConflict,
    InvalidShiftWindow,
    InvalidStaffLink,
    OverlappingShift,
    ShiftNotRespondable,
    cancel_shift,
    compute_coverage_warnings,
    copy_week,
    create_shift,
    publish_shift,
    publish_week,
    resolve_staff_link,
    respond_to_shift_as_staff,
    respond_to_shift_via_link,
)

router = APIRouter(tags=["roster"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_station_or_404(session: Session, venue_id: uuid.UUID, station_id: uuid.UUID) -> Station:
    station = session.query(Station).filter_by(id=station_id, venue_id=venue_id).one_or_none()
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    return station


def _get_staff_or_404(session: Session, venue_id: uuid.UUID, staff_id: uuid.UUID) -> Staff:
    staff = session.query(Staff).filter_by(id=staff_id, venue_id=venue_id).one_or_none()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")
    return staff


def _get_shift_or_404(session: Session, venue_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
    shift = session.query(Shift).filter_by(id=shift_id, venue_id=venue_id).one_or_none()
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return shift


def _dev_token_or_none(raw_token: str | None) -> str | None:
    """Same interim pattern as auth_service's dev_token: no email provider
    exists yet (Epic 10), so outside production the raw signed-link token
    is returned directly in the response instead of being emailed."""
    if raw_token is None or settings.environment == "production":
        return None
    return raw_token


# --- Shifts ----------------------------------------------------------------


@router.post("/venues/{venue_id}/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift_route(
    venue_id: uuid.UUID,
    body: ShiftCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ShiftOut:
    venue = _get_venue_or_404(session, venue_id)
    station = _get_station_or_404(session, venue_id, body.station_id)
    staff = _get_staff_or_404(session, venue_id, body.staff_id)
    try:
        return create_shift(
            session, venue=venue, actor=current_user, station=station, staff=staff,
            start_at=body.start_at, end_at=body.end_at,
        )
    except OverlappingShift as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidShiftWindow as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/venues/{venue_id}/shifts", response_model=list[ShiftOut])
def list_shifts(
    venue_id: uuid.UUID,
    week_start: date | None = Query(default=None),
    business_date: date | None = Query(default=None),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    """The 7-day roster grid's data source. Pass exactly one of week_start
    (returns that week's 7 business_dates) or business_date (a single
    day)."""
    if (week_start is None) == (business_date is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pass exactly one of week_start or business_date",
        )

    query = (
        session.query(Shift)
        .join(ServiceDay, Shift.service_day_id == ServiceDay.id)
        .filter(ServiceDay.venue_id == venue_id)
    )
    if week_start is not None:
        query = query.filter(
            ServiceDay.business_date >= week_start,
            ServiceDay.business_date < week_start + timedelta(days=7),
        )
    else:
        query = query.filter(ServiceDay.business_date == business_date)

    return query.order_by(Shift.start_at).all()


@router.get("/venues/{venue_id}/rosters/pdf")
def get_roster_pdf(
    venue_id: uuid.UUID,
    week_start: date = Query(...),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> Response:
    """Same read tier as list_shifts (any membership) — a printable version
    of the same week the roster grid shows, for posting on a kitchen wall
    or forwarding to a relief cook with no app access."""
    venue = _get_venue_or_404(session, venue_id)
    pdf_bytes = render_roster_pdf(session, venue=venue, week_start=week_start)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="roster-{week_start.isoformat()}.pdf"'},
    )


@router.get("/venues/{venue_id}/shifts/{shift_id}", response_model=ShiftOut)
def get_shift(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ShiftOut:
    return _get_shift_or_404(session, venue_id, shift_id)


@router.post("/venues/{venue_id}/shifts/{shift_id}/cancel", response_model=ShiftOut)
def cancel_shift_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ShiftOut:
    venue = _get_venue_or_404(session, venue_id)
    shift = _get_shift_or_404(session, venue_id, shift_id)
    return cancel_shift(session, venue=venue, actor=current_user, shift=shift)


@router.post("/venues/{venue_id}/shifts/{shift_id}/publish", response_model=PublishResultOut)
def publish_shift_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PublishResultOut:
    venue = _get_venue_or_404(session, venue_id)
    shift = _get_shift_or_404(session, venue_id, shift_id)
    try:
        result = publish_shift(session, venue=venue, actor=current_user, shift=shift)
    except CannotPublishCancelledShift as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return PublishResultOut(
        shift=result.shift, dev_staff_link_token=_dev_token_or_none(result.staff_link_raw_token)
    )


@router.post("/venues/{venue_id}/shifts/{shift_id}/respond", response_model=ShiftOut)
def respond_to_shift_route(
    venue_id: uuid.UUID,
    shift_id: uuid.UUID,
    body: StaffRespondRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> ShiftOut:
    """The "via login" response path — the caller must themselves be the
    Staff member this Shift is assigned to (their own Staff.user_id at this
    venue), not just any Member of the venue."""
    venue = _get_venue_or_404(session, venue_id)
    shift = _get_shift_or_404(session, venue_id, shift_id)

    staff = (
        session.query(Staff).filter_by(venue_id=venue_id, user_id=current_user.id).one_or_none()
    )
    if staff is None or staff.id != shift.staff_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This shift is not assigned to you"
        )

    try:
        respond_to_shift_as_staff(
            session, venue=venue, shift=shift, actor=current_user, response_status=body.response
        )
    except ShiftNotRespondable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return shift


# --- Roster-wide actions -----------------------------------------------


@router.post("/venues/{venue_id}/rosters/publish-week", response_model=list[PublishResultOut])
def publish_week_route(
    venue_id: uuid.UUID,
    body: PublishWeekRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PublishResultOut]:
    venue = _get_venue_or_404(session, venue_id)
    results = publish_week(session, venue=venue, actor=current_user, week_start=body.week_start)
    return [
        PublishResultOut(shift=r.shift, dev_staff_link_token=_dev_token_or_none(r.staff_link_raw_token))
        for r in results
    ]


@router.post("/venues/{venue_id}/rosters/copy-week", response_model=list[ShiftOut])
def copy_week_route(
    venue_id: uuid.UUID,
    body: CopyWeekRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[ShiftOut]:
    venue = _get_venue_or_404(session, venue_id)
    try:
        return copy_week(
            session, venue=venue, actor=current_user,
            source_week_start=body.source_week_start, target_week_start=body.target_week_start,
        )
    except CopyWeekConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get(
    "/venues/{venue_id}/service-days/{business_date}/coverage-warnings",
    response_model=list[CoverageWarningOut],
)
def coverage_warnings_route(
    venue_id: uuid.UUID,
    business_date: date,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[CoverageWarningOut]:
    venue = _get_venue_or_404(session, venue_id)
    return compute_coverage_warnings(session, venue=venue, business_date=business_date)


# --- Signed staff links (no login) --------------------------------------


def _staff_link_view(shift: Shift) -> StaffLinkShiftView:
    return StaffLinkShiftView(
        shift_id=shift.id,
        station_id=shift.station_id,
        staff_id=shift.staff_id,
        start_at=shift.start_at,
        end_at=shift.end_at,
        shift_status=shift.status,
        response_status=shift.response.status if shift.response else StaffResponseStatus.pending,
    )


@router.get("/staff-links/{token}", response_model=StaffLinkShiftView)
def view_shift_via_link(token: str, session: Session = Depends(get_session)) -> StaffLinkShiftView:
    try:
        shift, _staff = resolve_staff_link(session, raw_token=token)
    except InvalidStaffLink as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _staff_link_view(shift)


@router.post("/staff-links/{token}/respond", response_model=StaffLinkShiftView)
def respond_via_link_route(
    token: str, body: StaffRespondRequest, session: Session = Depends(get_session)
) -> StaffLinkShiftView:
    try:
        respond_to_shift_via_link(session, raw_token=token, response_status=body.response)
        shift, _staff = resolve_staff_link(session, raw_token=token)
    except InvalidStaffLink as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ShiftNotRespondable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _staff_link_view(shift)
