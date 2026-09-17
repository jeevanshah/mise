from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import MANAGEMENT_ROLES, get_current_user, require_membership
from app.api.schemas.kitchen_memory import (
    EquipmentItemIssueHistoryOut,
    LinkRecipeRequest,
    MenuItemDetailOut,
    RecipeCreateRequest,
    RecipeDetailOut,
    RecipeIngredientOut,
    RecipeOut,
    RecipeVersionCreateRequest,
    RecipeVersionOut,
    SearchResultOut,
)
from app.core.database import get_session
from app.models.equipment import EquipmentItem
from app.models.ingredient import Ingredient
from app.models.membership import Membership
from app.models.menu import MenuItem
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.models.user import User
from app.models.venue import Venue
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

router = APIRouter(tags=["kitchen-memory"])


def _get_venue_or_404(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:  # pragma: no cover — require_membership's FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _get_recipe_or_404(session: Session, venue_id: uuid.UUID, recipe_id: uuid.UUID) -> Recipe:
    recipe = session.query(Recipe).filter_by(id=recipe_id, venue_id=venue_id).one_or_none()
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


def _get_menu_item_or_404(session: Session, venue_id: uuid.UUID, menu_item_id: uuid.UUID) -> MenuItem:
    menu_item = session.query(MenuItem).filter_by(id=menu_item_id, venue_id=venue_id).one_or_none()
    if menu_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")
    return menu_item


def _get_equipment_item_or_404(session: Session, venue_id: uuid.UUID, equipment_item_id: uuid.UUID) -> EquipmentItem:
    item = session.query(EquipmentItem).filter_by(id=equipment_item_id, venue_id=venue_id).one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment item not found")
    return item


def _version_out(session: Session, version: RecipeVersion) -> RecipeVersionOut:
    rows = (
        session.query(RecipeIngredient, Ingredient.name)
        .join(Ingredient, RecipeIngredient.ingredient_id == Ingredient.id)
        .filter(RecipeIngredient.recipe_version_id == version.id)
        .all()
    )
    return RecipeVersionOut(
        id=version.id, recipe_id=version.recipe_id, version_no=version.version_no,
        yield_qty=version.yield_qty, yield_unit=version.yield_unit, prep_notes=version.prep_notes,
        ingredients=[
            RecipeIngredientOut(
                ingredient_id=line.ingredient_id, ingredient_name=name,
                quantity=line.quantity, unit=line.unit,
            )
            for line, name in rows
        ],
    )


def _recipe_detail_out(session: Session, recipe: Recipe) -> RecipeDetailOut:
    current = get_current_recipe_version(session, recipe=recipe)
    version_count = session.query(RecipeVersion).filter_by(recipe_id=recipe.id).count()
    return RecipeDetailOut(
        id=recipe.id, venue_id=recipe.venue_id, name=recipe.name,
        current_version=_version_out(session, current) if current is not None else None,
        version_count=version_count,
    )


# --- Recipes ---------------------------------------------------------------


@router.post("/venues/{venue_id}/recipes", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe_route(
    venue_id: uuid.UUID,
    body: RecipeCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> RecipeOut:
    venue = _get_venue_or_404(session, venue_id)
    return create_recipe(session, venue=venue, actor=current_user, name=body.name)


@router.get("/venues/{venue_id}/recipes", response_model=list[RecipeOut])
def list_recipes(
    venue_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[RecipeOut]:
    return session.query(Recipe).filter_by(venue_id=venue_id).order_by(Recipe.name).all()


@router.get("/venues/{venue_id}/recipes/{recipe_id}", response_model=RecipeDetailOut)
def get_recipe_route(
    venue_id: uuid.UUID,
    recipe_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> RecipeDetailOut:
    recipe = _get_recipe_or_404(session, venue_id, recipe_id)
    return _recipe_detail_out(session, recipe)


@router.get("/venues/{venue_id}/recipes/{recipe_id}/versions", response_model=list[RecipeVersionOut])
def list_recipe_versions(
    venue_id: uuid.UUID,
    recipe_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[RecipeVersionOut]:
    """Old versions "stay viewable" (locked AC) — the full history, oldest
    first, never just the current one."""
    recipe = _get_recipe_or_404(session, venue_id, recipe_id)
    versions = (
        session.query(RecipeVersion).filter_by(recipe_id=recipe.id).order_by(RecipeVersion.version_no).all()
    )
    return [_version_out(session, v) for v in versions]


@router.post(
    "/venues/{venue_id}/recipes/{recipe_id}/versions",
    response_model=RecipeVersionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_recipe_version_route(
    venue_id: uuid.UUID,
    recipe_id: uuid.UUID,
    body: RecipeVersionCreateRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> RecipeVersionOut:
    """"Editing" a Recipe always means creating a fresh version here — see
    kitchen_memory_service's own docstring for why there's no in-place
    update endpoint."""
    venue = _get_venue_or_404(session, venue_id)
    recipe = _get_recipe_or_404(session, venue_id, recipe_id)
    try:
        version = create_recipe_version(
            session, venue=venue, actor=current_user, recipe=recipe,
            yield_qty=body.yield_qty, yield_unit=body.yield_unit, prep_notes=body.prep_notes,
            ingredients=[
                RecipeIngredientLine(ingredient_id=line.ingredient_id, quantity=line.quantity, unit=line.unit)
                for line in body.ingredients
            ],
        )
    except UnknownIngredientForRecipe as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return _version_out(session, version)


# --- MenuItem <-> Recipe -----------------------------------------------


@router.post(
    "/venues/{venue_id}/menu-items/{menu_item_id}/recipes",
    response_model=MenuItemDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def link_recipe_to_menu_item_route(
    venue_id: uuid.UUID,
    menu_item_id: uuid.UUID,
    body: LinkRecipeRequest,
    current_user: User = Depends(get_current_user),
    membership: Membership = Depends(require_membership(*MANAGEMENT_ROLES)),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> MenuItemDetailOut:
    venue = _get_venue_or_404(session, venue_id)
    menu_item = _get_menu_item_or_404(session, venue_id, menu_item_id)
    recipe = _get_recipe_or_404(session, venue_id, body.recipe_id)
    try:
        link_menu_item_recipe(session, venue=venue, actor=current_user, menu_item=menu_item, recipe=recipe)
    except RecipeAlreadyLinkedToMenuItem as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _menu_item_detail_out(session, menu_item)


def _menu_item_detail_out(session: Session, menu_item: MenuItem) -> MenuItemDetailOut:
    recipes = get_recipes_for_menu_item(session, menu_item=menu_item)
    return MenuItemDetailOut(
        id=menu_item.id, venue_id=menu_item.venue_id, name=menu_item.name,
        recipes=[_recipe_detail_out(session, r) for r in recipes],
    )


@router.get("/venues/{venue_id}/menu-items/{menu_item_id}", response_model=MenuItemDetailOut)
def get_menu_item_route(
    venue_id: uuid.UUID,
    menu_item_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> MenuItemDetailOut:
    menu_item = _get_menu_item_or_404(session, venue_id, menu_item_id)
    return _menu_item_detail_out(session, menu_item)


# --- EquipmentItem issue history -----------------------------------------


@router.get(
    "/venues/{venue_id}/equipment-items/{equipment_item_id}/issues",
    response_model=EquipmentItemIssueHistoryOut,
)
def get_equipment_issue_history_route(
    venue_id: uuid.UUID,
    equipment_item_id: uuid.UUID,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> EquipmentItemIssueHistoryOut:
    """The full open+resolved history (locked AC) — the polished view
    EquipmentItem's own Epic-1 docstring promised for this epic."""
    equipment_item = _get_equipment_item_or_404(session, venue_id, equipment_item_id)
    return EquipmentItemIssueHistoryOut(
        equipment_item=equipment_item,
        issues=get_equipment_issue_history(session, equipment_item=equipment_item),
    )


# --- Search ----------------------------------------------------------------


@router.get("/venues/{venue_id}/kitchen-memory/search", response_model=list[SearchResultOut])
def search_route(
    venue_id: uuid.UUID,
    q: str,
    membership: Membership = Depends(require_membership()),  # noqa: ARG001
    session: Session = Depends(get_session),
) -> list[SearchResultOut]:
    venue = _get_venue_or_404(session, venue_id)
    results = search_kitchen_memory(session, venue=venue, query=q)
    return [
        SearchResultOut(
            result_type=r.result_type, entity_id=r.entity_id, title=r.title, matched_text=r.matched_text,
        )
        for r in results
    ]
