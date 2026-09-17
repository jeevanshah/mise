from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.pilot_metrics import (
    LogIncidentRequest,
    MinutesSavedRequest,
    PilotDecisionRequest,
    PilotMetricEventOut,
)
from app.core.database import get_session
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.models.venue import Venue
from app.services.pilot_metrics_service import (
    InvalidIncidentType,
    get_pilot_metrics,
    log_incident,
    record_minutes_saved,
    record_pilot_decision,
)

router = APIRouter(tags=["pilot-metrics"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.post(
    "/venues/{venue_id}/metrics/minutes-saved",
    response_model=PilotMetricEventOut,
    status_code=status.HTTP_201_CREATED,
)
def record_minutes_saved_route(
    venue_id: uuid.UUID,
    body: MinutesSavedRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PilotMetricEventOut:
    venue = _get_venue_or_404(session, venue_id)
    return record_minutes_saved(
        session, venue=venue, actor=current_user,
        week_start=body.week_start, minutes_saved=body.minutes_saved,
    )


@router.post(
    "/venues/{venue_id}/metrics/incidents", response_model=PilotMetricEventOut, status_code=status.HTTP_201_CREATED,
)
def log_incident_route(
    venue_id: uuid.UUID,
    body: LogIncidentRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PilotMetricEventOut:
    venue = _get_venue_or_404(session, venue_id)
    try:
        return log_incident(
            session, venue=venue, actor=current_user, business_date=body.business_date,
            incident_type=body.incident_type, description=body.description,
        )
    except InvalidIncidentType as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/venues/{venue_id}/metrics/pilot-decision",
    response_model=PilotMetricEventOut,
    status_code=status.HTTP_201_CREATED,
)
def record_pilot_decision_route(
    venue_id: uuid.UUID,
    body: PilotDecisionRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(MembershipRole.owner)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PilotMetricEventOut:
    """Owner-only (locked AC: "Owner's ... answer") — deliberately
    narrower than MANAGEMENT_ROLES, same tier as onboarding's venue
    settings edit."""
    venue = _get_venue_or_404(session, venue_id)
    return record_pilot_decision(
        session, venue=venue, actor=current_user,
        will_pay_at_proposed_price=body.will_pay_at_proposed_price, notes=body.notes,
    )


@router.get("/venues/{venue_id}/metrics", response_model=list[PilotMetricEventOut])
def get_pilot_metrics_route(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PilotMetricEventOut]:
    venue = _get_venue_or_404(session, venue_id)
    return get_pilot_metrics(session, venue=venue)
