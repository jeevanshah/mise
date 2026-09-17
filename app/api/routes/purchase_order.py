from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.purchase_order import (
    AddOrMergeLineRequest,
    LogDeliveryIssueRequest,
    MarkDeliveryRequest,
    PurchaseOrderOut,
    UpdateLineQuantityRequest,
)
from app.core.database import get_session
from app.models.membership import Membership
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus
from app.models.user import User
from app.models.venue import Venue
from app.services.supplier_order_service import (
    CannotModifyNonDraftOrder,
    CannotSendOrder,
    MissingOrderIdentity,
    PartialDeliveryRequiresLineNote,
    UnknownIngredient,
    UnknownSupplier,
    add_or_merge_line,
    log_delivery_issue,
    mark_delivery,
    send_purchase_order,
    update_line_quantity,
)

router = APIRouter(tags=["purchase-orders"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_purchase_order_or_404(session: Session, venue_id: uuid.UUID, po_id: uuid.UUID) -> PurchaseOrder:
    order = session.query(PurchaseOrder).filter_by(id=po_id, venue_id=venue_id).one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return order


def _get_line_or_404(
    session: Session, venue_id: uuid.UUID, po_id: uuid.UUID, line_id: uuid.UUID
) -> PurchaseOrderLine:
    line = (
        session.query(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
        .filter(
            PurchaseOrderLine.id == line_id,
            PurchaseOrderLine.purchase_order_id == po_id,
            PurchaseOrder.venue_id == venue_id,
        )
        .one_or_none()
    )
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order line not found")
    return line


@router.post(
    "/venues/{venue_id}/purchase-orders/lines",
    response_model=PurchaseOrderOut,
    status_code=status.HTTP_200_OK,
)
def add_or_merge_line_route(
    venue_id: uuid.UUID,
    body: AddOrMergeLineRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    """Finds/creates the open draft for (supplier, required_delivery_date
    or order_cycle) and adds this line — merging into an existing line for
    the same ingredient if one is already on that draft. This is the same
    function Quick Capture (Epic 6) calls directly at the service layer."""
    venue = _get_venue_or_404(session, venue_id)
    try:
        result = add_or_merge_line(
            session, venue=venue, actor=current_user,
            supplier_id=body.supplier_id, ingredient_id=body.ingredient_id,
            quantity=body.quantity, unit=body.unit,
            required_delivery_date=body.required_delivery_date, order_cycle=body.order_cycle,
        )
    except (UnknownSupplier, UnknownIngredient, MissingOrderIdentity) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return result.purchase_order


@router.patch(
    "/venues/{venue_id}/purchase-orders/{po_id}/lines/{line_id}",
    response_model=PurchaseOrderOut,
)
def update_line_quantity_route(
    venue_id: uuid.UUID,
    po_id: uuid.UUID,
    line_id: uuid.UUID,
    body: UpdateLineQuantityRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    venue = _get_venue_or_404(session, venue_id)
    line = _get_line_or_404(session, venue_id, po_id, line_id)
    try:
        update_line_quantity(session, venue=venue, actor=current_user, line=line, quantity=body.quantity)
    except CannotModifyNonDraftOrder as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return line.purchase_order


@router.get("/venues/{venue_id}/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    venue_id: uuid.UUID,
    order_status: PurchaseOrderStatus | None = Query(default=None, alias="status"),
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[PurchaseOrderOut]:
    query = session.query(PurchaseOrder).filter_by(venue_id=venue_id)
    if order_status is not None:
        query = query.filter_by(status=order_status)
    return query.order_by(PurchaseOrder.created_at.desc()).all()


@router.get("/venues/{venue_id}/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    venue_id: uuid.UUID,
    po_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    return _get_purchase_order_or_404(session, venue_id, po_id)


@router.post("/venues/{venue_id}/purchase-orders/{po_id}/send", response_model=PurchaseOrderOut)
def send_purchase_order_route(
    venue_id: uuid.UUID,
    po_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    venue = _get_venue_or_404(session, venue_id)
    order = _get_purchase_order_or_404(session, venue_id, po_id)
    try:
        return send_purchase_order(session, venue=venue, actor=current_user, purchase_order=order)
    except CannotSendOrder as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/venues/{venue_id}/purchase-orders/{po_id}/delivery", response_model=PurchaseOrderOut)
def mark_delivery_route(
    venue_id: uuid.UUID,
    po_id: uuid.UUID,
    body: MarkDeliveryRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    venue = _get_venue_or_404(session, venue_id)
    order = _get_purchase_order_or_404(session, venue_id, po_id)
    try:
        return mark_delivery(
            session, venue=venue, actor=current_user, purchase_order=order,
            partial=body.partial, line_notes=body.line_notes,
        )
    except PartialDeliveryRequiresLineNote as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post(
    "/venues/{venue_id}/purchase-orders/{po_id}/delivery-issues",
    response_model=PurchaseOrderOut,
    status_code=status.HTTP_201_CREATED,
)
def log_delivery_issue_route(
    venue_id: uuid.UUID,
    po_id: uuid.UUID,
    body: LogDeliveryIssueRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> PurchaseOrderOut:
    venue = _get_venue_or_404(session, venue_id)
    order = _get_purchase_order_or_404(session, venue_id, po_id)
    log_delivery_issue(
        session, venue=venue, actor=current_user, purchase_order=order,
        issue_type=body.issue_type, evidence=body.evidence, resolution=body.resolution,
    )
    session.refresh(order)
    return order
