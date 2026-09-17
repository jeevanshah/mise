from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditEvent
from app.models.user import User
from app.services.capture_service import confirm_capture, create_capture
from app.services.catalog_service import create_equipment_item, create_ingredient, create_menu_item, create_supplier
from app.services.handover_service import close_service_day
from app.services.kitchen_memory_service import (
    RecipeAlreadyLinkedToMenuItem,
    RecipeIngredientLine,
    UnknownIngredientForRecipe,
    create_recipe,
    create_recipe_version,
    get_current_recipe_version,
    get_equipment_issue_history,
    get_recipes_for_menu_item,
    link_menu_item_recipe,
    search_kitchen_memory,
)
from app.services.onboarding_service import create_organisation_with_venue
from app.services.service_day_service import get_or_create_service_day, open_service_day


def _owner_venue(session, label: str = "owner"):
    owner = User(email=f"{label}@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name=f"Test Co {label}", venue_name=f"Test Diner {label}"
    )
    return owner, venue


# --- Recipes / versions ------------------------------------------------


def test_create_recipe_version_creates_version_one(session):
    owner, venue = _owner_venue(session)
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    recipe = create_recipe(session, venue=venue, actor=owner, name="House Vinaigrette")

    version = create_recipe_version(
        session, venue=venue, actor=owner, recipe=recipe,
        yield_qty=Decimal("1"), yield_unit="litre", prep_notes="Whisk vigorously",
        ingredients=[RecipeIngredientLine(ingredient_id=onions.id, quantity=Decimal("2"), unit="kg")],
    )

    assert version.version_no == 1
    assert version.prep_notes == "Whisk vigorously"
    event = session.query(AuditEvent).filter_by(action="recipe_version.created").one()
    assert event.after_data["version_no"] == 1
    assert event.after_data["ingredient_count"] == 1


def test_editing_a_recipe_creates_a_new_version_old_one_stays_viewable(session):
    owner, venue = _owner_venue(session)
    onions = create_ingredient(session, venue=venue, actor=owner, name="Onions", unit="kg", ordering_unit="sack")
    recipe = create_recipe(session, venue=venue, actor=owner, name="House Vinaigrette")
    v1 = create_recipe_version(
        session, venue=venue, actor=owner, recipe=recipe, prep_notes="v1 notes",
        ingredients=[RecipeIngredientLine(ingredient_id=onions.id, quantity=Decimal("1"), unit="kg")],
    )

    v2 = create_recipe_version(
        session, venue=venue, actor=owner, recipe=recipe, prep_notes="v2 notes",
        ingredients=[RecipeIngredientLine(ingredient_id=onions.id, quantity=Decimal("2"), unit="kg")],
    )

    assert v2.version_no == 2
    session.refresh(v1)
    assert v1.prep_notes == "v1 notes"  # untouched — old version still viewable
    assert get_current_recipe_version(session, recipe=recipe).id == v2.id


def test_create_recipe_version_rejects_unknown_ingredient(session):
    owner, venue = _owner_venue(session, "owner1")
    other_owner, other_venue = _owner_venue(session, "owner2")
    foreign_ingredient = create_ingredient(
        session, venue=other_venue, actor=other_owner, name="Foreign", unit="kg", ordering_unit="sack",
    )
    recipe = create_recipe(session, venue=venue, actor=owner, name="House Vinaigrette")

    with pytest.raises(UnknownIngredientForRecipe):
        create_recipe_version(
            session, venue=venue, actor=owner, recipe=recipe,
            ingredients=[RecipeIngredientLine(ingredient_id=foreign_ingredient.id, quantity=Decimal("1"), unit="kg")],
        )


def test_recipe_version_with_no_ingredients_is_allowed(session):
    owner, venue = _owner_venue(session)
    recipe = create_recipe(session, venue=venue, actor=owner, name="Salt")
    version = create_recipe_version(session, venue=venue, actor=owner, recipe=recipe, ingredients=[])
    assert version.version_no == 1


# --- MenuItem <-> Recipe -------------------------------------------------


def test_link_menu_item_to_recipe_and_read_back(session):
    owner, venue = _owner_venue(session)
    recipe = create_recipe(session, venue=venue, actor=owner, name="Bun")
    menu_item = create_menu_item(session, venue=venue, actor=owner, name="Cheeseburger")

    link_menu_item_recipe(session, venue=venue, actor=owner, menu_item=menu_item, recipe=recipe)

    recipes = get_recipes_for_menu_item(session, menu_item=menu_item)
    assert [r.id for r in recipes] == [recipe.id]


def test_linking_the_same_recipe_twice_is_rejected(session):
    owner, venue = _owner_venue(session)
    recipe = create_recipe(session, venue=venue, actor=owner, name="Bun")
    menu_item = create_menu_item(session, venue=venue, actor=owner, name="Cheeseburger")
    link_menu_item_recipe(session, venue=venue, actor=owner, menu_item=menu_item, recipe=recipe)

    with pytest.raises(RecipeAlreadyLinkedToMenuItem):
        link_menu_item_recipe(session, venue=venue, actor=owner, menu_item=menu_item, recipe=recipe)


def test_menu_item_can_be_built_from_several_recipes(session):
    owner, venue = _owner_venue(session)
    bun = create_recipe(session, venue=venue, actor=owner, name="Bun")
    patty = create_recipe(session, venue=venue, actor=owner, name="Patty")
    menu_item = create_menu_item(session, venue=venue, actor=owner, name="Cheeseburger")
    link_menu_item_recipe(session, venue=venue, actor=owner, menu_item=menu_item, recipe=bun)
    link_menu_item_recipe(session, venue=venue, actor=owner, menu_item=menu_item, recipe=patty)

    recipes = get_recipes_for_menu_item(session, menu_item=menu_item)
    assert {r.name for r in recipes} == {"Bun", "Patty"}


# --- EquipmentItem issue history ------------------------------------------


def test_equipment_issue_history_includes_resolved_and_open_newest_first(session):
    owner, venue = _owner_venue(session)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    first_capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")
    _, first_issue = confirm_capture(session, venue=venue, actor=owner, capture=first_capture)
    second_capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken again")
    _, second_issue = confirm_capture(session, venue=venue, actor=owner, capture=second_capture)

    history = get_equipment_issue_history(session, equipment_item=mixer)

    assert [i.id for i in history] == [second_issue.id, first_issue.id]


def test_equipment_issue_history_empty_for_item_with_no_issues(session):
    owner, venue = _owner_venue(session)
    fridge = create_equipment_item(session, venue=venue, actor=owner, name="Walk-in Fridge")
    assert get_equipment_issue_history(session, equipment_item=fridge) == []


# --- Search ----------------------------------------------------------------


def test_search_finds_recipe_by_name(session):
    owner, venue = _owner_venue(session)
    create_recipe(session, venue=venue, actor=owner, name="House Vinaigrette")

    results = search_kitchen_memory(session, venue=venue, query="vinaigrette")

    assert len(results) == 1
    assert results[0].result_type == "recipe"


def test_search_finds_recipe_by_prep_notes(session):
    owner, venue = _owner_venue(session)
    recipe = create_recipe(session, venue=venue, actor=owner, name="Salad")
    create_recipe_version(session, venue=venue, actor=owner, recipe=recipe, prep_notes="Chiffonade the basil finely", ingredients=[])

    results = search_kitchen_memory(session, venue=venue, query="chiffonade")

    assert len(results) == 1
    assert results[0].entity_id == recipe.id


def test_search_finds_supplier_notes(session):
    owner, venue = _owner_venue(session)
    supplier = create_supplier(
        session, venue=venue, actor=owner, name="Fresh Co", notes="Deliveries arrive via the laneway entrance",
    )

    results = search_kitchen_memory(session, venue=venue, query="laneway")

    assert len(results) == 1
    assert results[0].result_type == "supplier"
    assert results[0].entity_id == supplier.id


def test_search_finds_equipment_issue_resolution_notes(session):
    owner, venue = _owner_venue(session)
    create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")
    capture = create_capture(session, venue=venue, actor=owner, raw_text="the stand mixer is broken")
    _, issue = confirm_capture(session, venue=venue, actor=owner, capture=capture)
    issue.resolution_notes = "Replaced the drive belt"
    session.add(issue)
    session.commit()

    results = search_kitchen_memory(session, venue=venue, query="drive belt")

    assert len(results) == 1
    assert results[0].result_type == "equipment_issue"
    assert results[0].entity_id == issue.id


def test_search_finds_past_handover_note(session):
    owner, venue = _owner_venue(session)
    day = get_or_create_service_day(session, venue=venue, business_date=date(2026, 6, 1))
    session.commit()
    day = open_service_day(session, service_day=day, venue=venue, actor=owner)
    handover = close_service_day(
        session, venue=venue, actor=owner, service_day=day, note="Ran out of the walk-in's backup compressor part",
    )

    results = search_kitchen_memory(session, venue=venue, query="compressor")

    assert len(results) == 1
    assert results[0].result_type == "handover"
    assert results[0].entity_id == handover.id


def test_search_is_venue_scoped(session):
    owner, venue = _owner_venue(session, "owner1")
    other_owner, other_venue = _owner_venue(session, "owner2")
    create_recipe(session, venue=other_venue, actor=other_owner, name="House Vinaigrette")

    results = search_kitchen_memory(session, venue=venue, query="vinaigrette")

    assert results == []


def test_search_with_blank_query_returns_nothing(session):
    owner, venue = _owner_venue(session)
    create_recipe(session, venue=venue, actor=owner, name="House Vinaigrette")

    assert search_kitchen_memory(session, venue=venue, query="") == []
    assert search_kitchen_memory(session, venue=venue, query="   ") == []
