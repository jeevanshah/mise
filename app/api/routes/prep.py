from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, PREP_EXECUTION_ROLES, get_current_user, require_membership
from app.api.schemas.prep import (
    ApplyPrepTemplateRequest,
    CarryForwardRequest,
    PrepTaskOut,
    PrepTaskStatusUpdateRequest,
    PrepTemplateCreateRequest,
    PrepTemplateDetailOut,
    PrepTemplateItemCreateRequest,
    PrepTemplateItemOut,
    PrepTemplateOut,
    PrintablePrepTaskOut,
)
from app.core.database import get_session
from app.models.membership import Membership
from app.models.prep import PrepTask, PrepTemplate
from app.models.service_day import ServiceDay
from app.models.station import Station
from app.models.user import User
from app.models.venue import Venue
from app.services.prep_service import (
    add_template_item,
    apply_prep_template,
    carry_forward_prep_tasks,
    create_prep_template,
    update_prep_task_status,
)
from app.services.service_day_service import ServiceDayIsClosed, get_or_create_service_day

router = APIRouter(tags=["prep"])


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


def _get_template_or_404(session: Session, venue_id: uuid.UUID, template_id: uuid.UUID) -> PrepTemplate:
    template = session.query(PrepTemplate).filter_by(id=template_id, venue_id=venue_id).one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prep template not found")
    return template


def _get_task_or_404(session: Session, venue_id: uuid.UUID, task_id: uuid.UUID) -> PrepTask:
    task = session.query(PrepTask).filter_by(id=task_id, venue_id=venue_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prep task not found")
    return task


def _get_service_day_or_none(session: Session, venue_id: uuid.UUID, business_date: date) -> ServiceDay | None:
    return session.query(ServiceDay).filter_by(venue_id=venue_id, business_date=business_date).one_or_none()


# --- Templates -----------------------------------------------------------


@router.post(
    "/venues/{venue_id}/prep-templates", response_model=PrepTemplateOut, status_code=status.HTTP_201_CREATED
)
def create_template_route(
    venue_id: uuid.UUID,
    body: PrepTemplateCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PrepTemplateOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_prep_template(session, venue=venue, actor=current_user, name=body.name)


@router.get("/venues/{venue_id}/prep-templates", response_model=list[PrepTemplateOut])
def list_templates_route(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PrepTemplateOut]:
    return session.query(PrepTemplate).filter_by(venue_id=venue_id).order_by(PrepTemplate.name).all()


@router.get("/venues/{venue_id}/prep-templates/{template_id}", response_model=PrepTemplateDetailOut)
def get_template_route(
    venue_id: uuid.UUID,
    template_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PrepTemplateDetailOut:
    template = _get_template_or_404(session, venue_id, template_id)
    return PrepTemplateDetailOut(
        id=template.id, venue_id=template.venue_id, name=template.name, items=template.items
    )


@router.post(
    "/venues/{venue_id}/prep-templates/{template_id}/items",
    response_model=PrepTemplateItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_template_item_route(
    venue_id: uuid.UUID,
    template_id: uuid.UUID,
    body: PrepTemplateItemCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PrepTemplateItemOut:
    venue = _get_venue_or_404(session, venue_id)
    template = _get_template_or_404(session, venue_id, template_id)
    station = _get_station_or_404(session, venue_id, body.station_id)
    return add_template_item(
        session, venue=venue, actor=current_user, template=template, station=station,
        item=body.item, quantity=body.quantity, unit=body.unit, priority=body.priority,
    )


# --- Prep tasks ------------------------------------------------------------


@router.post(
    "/venues/{venue_id}/service-days/{business_date}/prep-tasks/apply-template",
    response_model=list[PrepTaskOut],
)
def apply_template_route(
    venue_id: uuid.UUID,
    business_date: date,
    body: ApplyPrepTemplateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PrepTaskOut]:
    venue = _get_venue_or_404(session, venue_id)
    template = _get_template_or_404(session, venue_id, body.template_id)
    service_day = get_or_create_service_day(session, venue=venue, business_date=business_date)
    try:
        return apply_prep_template(
            session, venue=venue, actor=current_user, template=template, service_day=service_day,
            added_after_close=body.added_after_close,
        )
    except ServiceDayIsClosed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/venues/{venue_id}/service-days/{business_date}/prep-tasks", response_model=list[PrepTaskOut]
)
def list_prep_tasks_route(
    venue_id: uuid.UUID,
    business_date: date,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PrepTaskOut]:
    service_day = _get_service_day_or_none(session, venue_id, business_date)
    if service_day is None:
        return []
    return (
        session.query(PrepTask)
        .filter_by(service_day_id=service_day.id)
        .order_by(PrepTask.priority.desc(), PrepTask.created_at)
        .all()
    )


@router.get(
    "/venues/{venue_id}/service-days/{business_date}/prep-tasks/printable",
    response_model=list[PrintablePrepTaskOut],
)
def printable_prep_list_route(
    venue_id: uuid.UUID,
    business_date: date,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PrintablePrepTaskOut]:
    service_day = _get_service_day_or_none(session, venue_id, business_date)
    if service_day is None:
        return []
    rows = (
        session.query(PrepTask, Station.name)
        .join(Station, PrepTask.station_id == Station.id)
        .filter(PrepTask.service_day_id == service_day.id)
        .order_by(PrepTask.priority.desc(), PrepTask.created_at)
        .all()
    )
    return [
        PrintablePrepTaskOut(
            station_id=task.station_id, station_name=station_name, item=task.item,
            quantity=task.quantity, unit=task.unit, priority=task.priority, status=task.status,
        )
        for task, station_name in rows
    ]


@router.patch("/venues/{venue_id}/prep-tasks/{task_id}/status", response_model=PrepTaskOut)
def update_prep_task_status_route(
    venue_id: uuid.UUID,
    task_id: uuid.UUID,
    body: PrepTaskStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*PREP_EXECUTION_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PrepTaskOut:
    venue = _get_venue_or_404(session, venue_id)
    task = _get_task_or_404(session, venue_id, task_id)
    try:
        return update_prep_task_status(session, venue=venue, actor=current_user, task=task, status=body.status)
    except ServiceDayIsClosed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/venues/{venue_id}/service-days/{business_date}/prep-tasks/carry-forward",
    response_model=list[PrepTaskOut],
)
def carry_forward_route(
    venue_id: uuid.UUID,
    business_date: date,
    body: CarryForwardRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PrepTaskOut]:
    venue = _get_venue_or_404(session, venue_id)
    from_service_day = _get_service_day_or_none(session, venue_id, business_date)
    if from_service_day is None:
        return []
    to_service_day = get_or_create_service_day(session, venue=venue, business_date=body.to_business_date)
    return carry_forward_prep_tasks(
        session, venue=venue, actor=current_user, from_service_day=from_service_day, to_service_day=to_service_day
    )
