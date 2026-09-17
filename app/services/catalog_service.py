"""
Epic 1 step 7 — Suppliers/Ingredients/Menu/Equipment endpoints (service
layer).

AC: "Suppliers, Ingredients, MenuItems, EquipmentItems all creatable from
onboarding — Quick Capture (Epic 6) needs all of these to already exist to
fuzzy-match against." Recipe/RecipeVersion/RecipeIngredient stay schema-only
per the locked Epic 1 entity list ("skeleton") — their CRUD surface belongs
to Epic 9 (Kitchen Memory Interface), not here.

Same audited_transaction pattern as staffing_service/onboarding_service.
"""

from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy.orm import Session

from app.models.equipment import EquipmentItem
from app.models.ingredient import Ingredient
from app.models.menu import MenuItem
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class UnknownPreferredSupplier(Exception):
    """preferred_supplier_id must reference a Supplier at the SAME venue —
    silently accepting a cross-venue supplier id would be a tenancy leak,
    not a foreign-key nicety."""


def create_supplier(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    name: str,
    contact_email: str | None = None,
    order_days: str | None = None,
    cutoff_time: time | None = None,
) -> Supplier:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        supplier = Supplier(
            venue_id=venue.id, name=name, contact_email=contact_email,
            order_days=order_days, cutoff_time=cutoff_time,
        )
        session.add(supplier)
        session.flush()
        audit.record(
            action="supplier.created", entity_type="supplier", entity_id=supplier.id,
            after={"name": supplier.name},
        )
    return supplier


def create_ingredient(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    name: str,
    unit: str,
    ordering_unit: str,
    preferred_supplier_id: uuid.UUID | None = None,
) -> Ingredient:
    if preferred_supplier_id is not None:
        supplier = (
            session.query(Supplier)
            .filter_by(id=preferred_supplier_id, venue_id=venue.id)
            .one_or_none()
        )
        if supplier is None:
            raise UnknownPreferredSupplier(
                f"Supplier {preferred_supplier_id} does not exist at this venue"
            )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        ingredient = Ingredient(
            venue_id=venue.id, name=name, unit=unit, ordering_unit=ordering_unit,
            preferred_supplier_id=preferred_supplier_id,
        )
        session.add(ingredient)
        session.flush()
        audit.record(
            action="ingredient.created", entity_type="ingredient", entity_id=ingredient.id,
            after={"name": ingredient.name, "unit": unit, "ordering_unit": ordering_unit},
        )
    return ingredient


def create_menu_item(session: Session, *, venue: Venue, actor: User, name: str) -> MenuItem:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        menu_item = MenuItem(venue_id=venue.id, name=name)
        session.add(menu_item)
        session.flush()
        audit.record(
            action="menu_item.created", entity_type="menu_item", entity_id=menu_item.id,
            after={"name": menu_item.name},
        )
    return menu_item


def create_equipment_item(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    name: str,
    location: str | None = None,
    repair_contact: str | None = None,
) -> EquipmentItem:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        item = EquipmentItem(
            venue_id=venue.id, name=name, location=location, repair_contact=repair_contact,
        )
        session.add(item)
        session.flush()
        audit.record(
            action="equipment_item.created", entity_type="equipment_item", entity_id=item.id,
            after={"name": item.name, "status": item.status.value},
        )
    return item
