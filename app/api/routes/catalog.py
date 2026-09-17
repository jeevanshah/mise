from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.catalog import (
    EquipmentItemCreateRequest,
    EquipmentItemOut,
    IngredientCreateRequest,
    IngredientOut,
    MenuItemCreateRequest,
    MenuItemOut,
    SupplierCreateRequest,
    SupplierOut,
)
from app.core.database import get_session
from app.models.equipment import EquipmentItem
from app.models.ingredient import Ingredient
from app.models.membership import Membership
from app.models.menu import MenuItem
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.catalog_service import (
    UnknownPreferredSupplier,
    create_equipment_item,
    create_ingredient,
    create_menu_item,
    create_supplier,
)

router = APIRouter(tags=["catalog"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


# --- Suppliers -----------------------------------------------------------


@router.post("/venues/{venue_id}/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier_route(
    venue_id: uuid.UUID,
    body: SupplierCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> SupplierOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_supplier(
        session, venue=venue, actor=current_user, name=body.name,
        contact_email=body.contact_email, order_days=body.order_days, cutoff_time=body.cutoff_time,
    )


@router.get("/venues/{venue_id}/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[SupplierOut]:
    return session.query(Supplier).filter_by(venue_id=venue_id).order_by(Supplier.name).all()


# --- Ingredients -----------------------------------------------------------


@router.post("/venues/{venue_id}/ingredients", response_model=IngredientOut, status_code=status.HTTP_201_CREATED)
def create_ingredient_route(
    venue_id: uuid.UUID,
    body: IngredientCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> IngredientOut:
    venue = _get_venue_or_404(session, venue_id)
    try:
        return create_ingredient(
            session, venue=venue, actor=current_user, name=body.name, unit=body.unit,
            ordering_unit=body.ordering_unit, preferred_supplier_id=body.preferred_supplier_id,
        )
    except UnknownPreferredSupplier as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/venues/{venue_id}/ingredients", response_model=list[IngredientOut])
def list_ingredients(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[IngredientOut]:
    return session.query(Ingredient).filter_by(venue_id=venue_id).order_by(Ingredient.name).all()


# --- Menu items --------------------------------------------------------


@router.post("/venues/{venue_id}/menu-items", response_model=MenuItemOut, status_code=status.HTTP_201_CREATED)
def create_menu_item_route(
    venue_id: uuid.UUID,
    body: MenuItemCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> MenuItemOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_menu_item(session, venue=venue, actor=current_user, name=body.name)


@router.get("/venues/{venue_id}/menu-items", response_model=list[MenuItemOut])
def list_menu_items(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[MenuItemOut]:
    return session.query(MenuItem).filter_by(venue_id=venue_id).order_by(MenuItem.name).all()


# --- Equipment items --------------------------------------------------


@router.post("/venues/{venue_id}/equipment-items", response_model=EquipmentItemOut, status_code=status.HTTP_201_CREATED)
def create_equipment_item_route(
    venue_id: uuid.UUID,
    body: EquipmentItemCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> EquipmentItemOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_equipment_item(
        session, venue=venue, actor=current_user, name=body.name,
        location=body.location, repair_contact=body.repair_contact,
    )


@router.get("/venues/{venue_id}/equipment-items", response_model=list[EquipmentItemOut])
def list_equipment_items(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[EquipmentItemOut]:
    return session.query(EquipmentItem).filter_by(venue_id=venue_id).order_by(EquipmentItem.name).all()
