import pytest

from app.models.audit import AuditEvent
from app.models.user import User
from app.services.catalog_service import (
    UnknownPreferredSupplier,
    create_equipment_item,
    create_ingredient,
    create_menu_item,
    create_supplier,
)
from app.services.onboarding_service import create_organisation_with_venue


def _owner_and_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_create_supplier_writes_audit_event(session):
    owner, venue = _owner_and_venue(session)
    supplier = create_supplier(session, venue=venue, actor=owner, name="Farm Fresh")

    assert supplier.venue_id == venue.id
    assert session.query(AuditEvent).filter_by(action="supplier.created").count() == 1


def test_create_ingredient_with_valid_preferred_supplier(session):
    owner, venue = _owner_and_venue(session)
    supplier = create_supplier(session, venue=venue, actor=owner, name="Farm Fresh")

    ingredient = create_ingredient(
        session, venue=venue, actor=owner, name="Tomato", unit="kg", ordering_unit="crate",
        preferred_supplier_id=supplier.id,
    )
    assert ingredient.preferred_supplier_id == supplier.id


def test_create_ingredient_rejects_supplier_from_another_venue(session):
    owner, venue = _owner_and_venue(session)
    _, other_venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Other Co", venue_name="Other Diner"
    )
    other_supplier = create_supplier(session, venue=other_venue, actor=owner, name="Other Supplier")

    with pytest.raises(UnknownPreferredSupplier):
        create_ingredient(
            session, venue=venue, actor=owner, name="Tomato", unit="kg", ordering_unit="crate",
            preferred_supplier_id=other_supplier.id,
        )


def test_create_menu_item(session):
    owner, venue = _owner_and_venue(session)
    item = create_menu_item(session, venue=venue, actor=owner, name="Cheeseburger")
    assert item.name == "Cheeseburger"


def test_create_equipment_item_defaults_to_active(session):
    owner, venue = _owner_and_venue(session)
    from app.models.equipment import EquipmentStatus

    item = create_equipment_item(session, venue=venue, actor=owner, name="Walk-in Fridge")
    assert item.status == EquipmentStatus.active
