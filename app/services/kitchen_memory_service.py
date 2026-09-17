"""
Epic 9 — Kitchen Memory Interface. Recipe/RecipeVersion/RecipeIngredient
have existed as schema-only tables since Epic 1 (the locked entity list
calls them a "skeleton") — this module is their first CRUD surface, plus
the MenuItem<->Recipe link, the polished EquipmentItem issue history Epic
1's own docstring promised, and cross-entity full-text search.

Versioning (locked AC + RecipeVersion's own docstring): "editing" a Recipe
never mutates an existing RecipeVersion in place — it creates a new one
with the next version_no. Old versions stay queryable forever. "Current"
is simply the highest version_no for that Recipe, always a derived read,
never a stored flag (same reasoning as ServiceDay's business_date or
AttendanceEvent's "current status").

No new TABLES (locked AC) — the one schema change this epic makes is a
single nullable `Supplier.notes` column (see that model's own docstring),
needed because "full-text search spans ... Supplier notes" and no existing
free-text field on Supplier could serve that purpose.

Search uses Postgres's built-in to_tsvector/plainto_tsquery computed
inline at query time — no new tsvector column or index, consistent with
"no new tables" and with this codebase's general preference for the
simplest mechanism that's actually correct (see capture_classifier's
stdlib-difflib-over-embeddings choice for the same reasoning applied
elsewhere).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.equipment import EquipmentIssue, EquipmentItem
from app.models.handover import Handover
from app.models.ingredient import Ingredient
from app.models.menu import MenuItem
from app.models.recipe import MenuItemRecipe, Recipe, RecipeIngredient, RecipeVersion
from app.models.service_day import ServiceDay
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


class UnknownIngredientForRecipe(Exception):
    """A RecipeIngredient's ingredient_id must reference an Ingredient at
    the same venue — same tenancy reasoning as
    catalog_service.UnknownPreferredSupplier."""


class RecipeAlreadyLinkedToMenuItem(Exception):
    """Linking the same (menu_item, recipe) pair twice is a 409, not a
    silent no-op — MenuItemRecipe has no other field to update, so a
    second call is either a mistake or belongs to unlink-then-relink, not
    an implicit success."""


@dataclass
class RecipeIngredientLine:
    ingredient_id: uuid.UUID
    quantity: Decimal
    unit: str


def create_recipe(session: Session, *, venue: Venue, actor: User, name: str) -> Recipe:
    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        recipe = Recipe(venue_id=venue.id, name=name)
        session.add(recipe)
        session.flush()
        audit.record(
            action="recipe.created", entity_type="recipe", entity_id=recipe.id, after={"name": name},
        )
    return recipe


def get_current_recipe_version(session: Session, *, recipe: Recipe) -> RecipeVersion | None:
    """The highest version_no for this Recipe — a derived read, never a
    stored "is_current" flag (see this module's own docstring)."""
    return (
        session.query(RecipeVersion)
        .filter_by(recipe_id=recipe.id)
        .order_by(RecipeVersion.version_no.desc())
        .first()
    )


def create_recipe_version(
    session: Session,
    *,
    venue: Venue,
    actor: User,
    recipe: Recipe,
    yield_qty: Decimal | None = None,
    yield_unit: str | None = None,
    prep_notes: str | None = None,
    ingredients: list[RecipeIngredientLine],
) -> RecipeVersion:
    """Always creates a NEW version — there is no "update a RecipeVersion"
    operation (locked AC + the model's own docstring: "old versions stay
    viewable — nothing is ever overwritten in place"). version_no is one
    past whatever the current highest is (1 for a brand-new Recipe)."""
    current = get_current_recipe_version(session, recipe=recipe)
    next_version_no = (current.version_no + 1) if current is not None else 1

    validated_ingredient_ids: set[uuid.UUID] = set()
    for line in ingredients:
        if line.ingredient_id not in validated_ingredient_ids:
            exists = (
                session.query(Ingredient).filter_by(id=line.ingredient_id, venue_id=venue.id).one_or_none()
            )
            if exists is None:
                raise UnknownIngredientForRecipe(
                    f"Ingredient {line.ingredient_id} does not exist at this venue"
                )
            validated_ingredient_ids.add(line.ingredient_id)

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        version = RecipeVersion(
            recipe_id=recipe.id, version_no=next_version_no,
            yield_qty=yield_qty, yield_unit=yield_unit, prep_notes=prep_notes,
        )
        session.add(version)
        session.flush()
        for line in ingredients:
            session.add(
                RecipeIngredient(
                    recipe_version_id=version.id, ingredient_id=line.ingredient_id,
                    quantity=line.quantity, unit=line.unit,
                )
            )
        session.flush()
        audit.record(
            action="recipe_version.created", entity_type="recipe_version", entity_id=version.id,
            after={
                "recipe_id": str(recipe.id), "version_no": next_version_no,
                "ingredient_count": len(ingredients),
            },
        )
    return version


def link_menu_item_recipe(
    session: Session, *, venue: Venue, actor: User, menu_item: MenuItem, recipe: Recipe
) -> MenuItemRecipe:
    existing = (
        session.query(MenuItemRecipe)
        .filter_by(menu_item_id=menu_item.id, recipe_id=recipe.id)
        .one_or_none()
    )
    if existing is not None:
        raise RecipeAlreadyLinkedToMenuItem(
            f"MenuItem {menu_item.id} is already linked to Recipe {recipe.id}"
        )

    with audited_transaction(
        session, organisation_id=venue.organisation_id, venue_id=venue.id, actor_user_id=actor.id
    ) as audit:
        link = MenuItemRecipe(menu_item_id=menu_item.id, recipe_id=recipe.id)
        session.add(link)
        session.flush()
        audit.record(
            action="menu_item_recipe.linked", entity_type="menu_item_recipe",
            entity_id=f"{menu_item.id}:{recipe.id}",
            after={"menu_item_id": str(menu_item.id), "recipe_id": str(recipe.id)},
        )
    return link


def get_recipes_for_menu_item(session: Session, *, menu_item: MenuItem) -> list[Recipe]:
    """"MenuItem detail view shows which Recipe(s)/components it's built
    from" (locked AC) — the recipes themselves; call
    get_current_recipe_version per recipe for its current ingredients."""
    return (
        session.query(Recipe)
        .join(MenuItemRecipe, MenuItemRecipe.recipe_id == Recipe.id)
        .filter(MenuItemRecipe.menu_item_id == menu_item.id)
        .order_by(Recipe.name)
        .all()
    )


def get_equipment_issue_history(session: Session, *, equipment_item: EquipmentItem) -> list[EquipmentIssue]:
    """Full history — open AND resolved — newest first. The "polished
    issue-history view" EquipmentItem's own Epic-1 docstring promised for
    this epic; app/services/handover_service.get_open_equipment_issues
    covers only the "currently open, venue-wide" slice this needs, not the
    full per-item timeline."""
    return (
        session.query(EquipmentIssue)
        .filter_by(equipment_item_id=equipment_item.id)
        .order_by(EquipmentIssue.opened_at.desc())
        .all()
    )


@dataclass
class SearchResult:
    result_type: str  # "recipe" | "supplier" | "equipment_issue" | "handover"
    entity_id: uuid.UUID
    title: str
    matched_text: str


def _tsquery_matches(column, query: str):
    return func.to_tsvector("english", func.coalesce(column, "")).op("@@")(
        func.plainto_tsquery("english", query)
    )


def search_kitchen_memory(session: Session, *, venue: Venue, query: str) -> list[SearchResult]:
    """Full-text search across exactly the four locked-AC surfaces: Recipes
    (name + any version's prep_notes), Supplier notes, EquipmentItem
    history (issue resolution_notes), and past Handovers (their note).
    Postgres to_tsvector/plainto_tsquery, computed inline — see this
    module's own docstring for why no new column/index is introduced for
    it. Results are grouped by type, not globally ranked — a chef scanning
    results cares more about "which recipe" than a cross-type relevance
    score four unrelated tables can't meaningfully share."""
    if not query or not query.strip():
        return []

    results: list[SearchResult] = []

    name_matches = (
        session.query(Recipe)
        .filter(Recipe.venue_id == venue.id, _tsquery_matches(Recipe.name, query))
        .all()
    )
    notes_matches = (
        session.query(Recipe, RecipeVersion.prep_notes)
        .join(RecipeVersion, RecipeVersion.recipe_id == Recipe.id)
        .filter(Recipe.venue_id == venue.id, _tsquery_matches(RecipeVersion.prep_notes, query))
        .all()
    )
    seen_recipe_ids: set[uuid.UUID] = set()
    for recipe in name_matches:
        seen_recipe_ids.add(recipe.id)
        results.append(SearchResult(result_type="recipe", entity_id=recipe.id, title=recipe.name, matched_text=recipe.name))
    for recipe, prep_notes in notes_matches:
        if recipe.id in seen_recipe_ids:
            continue
        seen_recipe_ids.add(recipe.id)
        results.append(
            SearchResult(result_type="recipe", entity_id=recipe.id, title=recipe.name, matched_text=prep_notes or "")
        )

    supplier_matches = (
        session.query(Supplier)
        .filter(Supplier.venue_id == venue.id, _tsquery_matches(Supplier.notes, query))
        .all()
    )
    for supplier in supplier_matches:
        results.append(
            SearchResult(
                result_type="supplier", entity_id=supplier.id, title=supplier.name,
                matched_text=supplier.notes or "",
            )
        )

    issue_matches = (
        session.query(EquipmentIssue, EquipmentItem.name)
        .join(EquipmentItem, EquipmentIssue.equipment_item_id == EquipmentItem.id)
        .filter(EquipmentItem.venue_id == venue.id, _tsquery_matches(EquipmentIssue.resolution_notes, query))
        .all()
    )
    for issue, equipment_item_name in issue_matches:
        results.append(
            SearchResult(
                result_type="equipment_issue", entity_id=issue.id,
                title=f"{equipment_item_name} — {issue.priority.value} priority issue",
                matched_text=issue.resolution_notes or "",
            )
        )

    handover_matches = (
        session.query(Handover, ServiceDay.business_date)
        .join(ServiceDay, Handover.service_day_id == ServiceDay.id)
        .filter(Handover.venue_id == venue.id, _tsquery_matches(Handover.note, query))
        .all()
    )
    for handover, business_date in handover_matches:
        results.append(
            SearchResult(
                result_type="handover", entity_id=handover.id, title=f"Handover — {business_date.isoformat()}",
                matched_text=handover.note or "",
            )
        )

    return results
