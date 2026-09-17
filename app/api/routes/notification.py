from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, require_membership
from app.api.schemas.notification import SentNotificationOut
from app.core.database import get_session
from app.models.membership import Membership
from app.models.venue import Venue
from app.services.notification_service import run_notification_checks

router = APIRouter(tags=["notifications"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.post("/venues/{venue_id}/notifications/run-checks", response_model=list[SentNotificationOut])
def run_notification_checks_route(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[SentNotificationOut]:
    """The three chef-facing checks (order cut-offs, unfilled shifts,
    stale equipment issues) have no scheduler to run them from in this
    backend build — this is that trigger, exposed as an explicit, audited,
    manually-triggerable action instead. In production this would be
    invoked on an interval (e.g. every 15-30 minutes) rather than by a
    person, but it's proven end to end via a real endpoint here, the same
    reasoning as Epic 1's `POST .../service-days/start` existing before
    anything automatically opened a ServiceDay."""
    venue = _get_venue_or_404(session, venue_id)
    return run_notification_checks(session, venue=venue)
