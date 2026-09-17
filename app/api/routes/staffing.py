from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.staffing import (
    CoverageRuleCreateRequest,
    CoverageRuleOut,
    StaffCreateRequest,
    StaffDetailOut,
    StaffOut,
    StaffSkillCreateRequest,
    StaffSkillOut,
    StationCreateRequest,
    StationOut,
)
from app.core.database import get_session
from app.models.membership import Membership
from app.models.staff import Staff
from app.models.station import Station, StationCoverageRule
from app.models.user import User
from app.models.venue import Venue
from app.services.staffing_service import (
    DuplicateCoverageRule,
    DuplicateStaffSkill,
    InvalidCoverageWindow,
    add_staff_skill,
    create_coverage_rule,
    create_staff,
    create_station,
)

router = APIRouter(tags=["staffing"])


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


# --- Stations --------------------------------------------------------------


@router.post("/venues/{venue_id}/stations", response_model=StationOut, status_code=status.HTTP_201_CREATED)
def create_station_route(
    venue_id: uuid.UUID,
    body: StationCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> StationOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_station(session, venue=venue, actor=current_user, name=body.name)


@router.get("/venues/{venue_id}/stations", response_model=list[StationOut])
def list_stations(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[StationOut]:
    return session.query(Station).filter_by(venue_id=venue_id).order_by(Station.name).all()


# --- Staff -------------------------------------------------------------


@router.post("/venues/{venue_id}/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff_route(
    venue_id: uuid.UUID,
    body: StaffCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> StaffOut:
    venue = _get_venue_or_404(session, venue_id)
    if body.user_id is not None and session.get(User, body.user_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="user_id does not exist")
    return create_staff(session, venue=venue, actor=current_user, name=body.name, user_id=body.user_id)


@router.get("/venues/{venue_id}/staff", response_model=list[StaffOut])
def list_staff(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[StaffOut]:
    return session.query(Staff).filter_by(venue_id=venue_id).order_by(Staff.name).all()


@router.get("/venues/{venue_id}/staff/{staff_id}", response_model=StaffDetailOut)
def get_staff(
    venue_id: uuid.UUID,
    staff_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> StaffDetailOut:
    staff = _get_staff_or_404(session, venue_id, staff_id)
    return StaffDetailOut(
        id=staff.id, venue_id=staff.venue_id, name=staff.name, user_id=staff.user_id,
        skills=staff.skills,
    )


@router.post(
    "/venues/{venue_id}/staff/{staff_id}/skills",
    response_model=StaffSkillOut,
    status_code=status.HTTP_201_CREATED,
)
def add_staff_skill_route(
    venue_id: uuid.UUID,
    staff_id: uuid.UUID,
    body: StaffSkillCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> StaffSkillOut:
    venue = _get_venue_or_404(session, venue_id)
    staff = _get_staff_or_404(session, venue_id, staff_id)
    station = _get_station_or_404(session, venue_id, body.station_id)
    try:
        return add_staff_skill(
            session, venue=venue, actor=current_user, staff=staff, station=station,
            trained=body.trained,
        )
    except DuplicateStaffSkill:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill already recorded for this station")


# --- Coverage rules ----------------------------------------------------


@router.post(
    "/venues/{venue_id}/stations/{station_id}/coverage-rules",
    response_model=CoverageRuleOut,
    status_code=status.HTTP_201_CREATED,
)
def create_coverage_rule_route(
    venue_id: uuid.UUID,
    station_id: uuid.UUID,
    body: CoverageRuleCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> CoverageRuleOut:
    venue = _get_venue_or_404(session, venue_id)
    station = _get_station_or_404(session, venue_id, station_id)
    try:
        return create_coverage_rule(
            session,
            venue=venue,
            actor=current_user,
            station=station,
            day_of_week=body.day_of_week,
            window_start=body.window_start,
            window_end=body.window_end,
            minimum_staff=body.minimum_staff,
        )
    except InvalidCoverageWindow as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except DuplicateCoverageRule as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/venues/{venue_id}/stations/{station_id}/coverage-rules",
    response_model=list[CoverageRuleOut],
)
def list_coverage_rules(
    venue_id: uuid.UUID,
    station_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[CoverageRuleOut]:
    _get_station_or_404(session, venue_id, station_id)
    return (
        session.query(StationCoverageRule)
        .filter_by(venue_id=venue_id, station_id=station_id)
        .order_by(StationCoverageRule.day_of_week, StationCoverageRule.window_start)
        .all()
    )
