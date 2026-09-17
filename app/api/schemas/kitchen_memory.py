from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.chef_brief import EquipmentIssueOut
from app.api.schemas.catalog import EquipmentItemOut, MenuItemOut


class RecipeCreateRequest(BaseModel):
    name: str


class RecipeOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class RecipeIngredientLineIn(BaseModel):
    ingredient_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str


class RecipeVersionCreateRequest(BaseModel):
    yield_qty: Decimal | None = None
    yield_unit: str | None = None
    prep_notes: str | None = None
    ingredients: list[RecipeIngredientLineIn] = []


class RecipeIngredientOut(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_name: str
    quantity: Decimal
    unit: str


class RecipeVersionOut(BaseModel):
    id: uuid.UUID
    recipe_id: uuid.UUID
    version_no: int
    yield_qty: Decimal | None
    yield_unit: str | None
    prep_notes: str | None
    ingredients: list[RecipeIngredientOut]


class RecipeDetailOut(RecipeOut):
    current_version: RecipeVersionOut | None
    version_count: int


class LinkRecipeRequest(BaseModel):
    recipe_id: uuid.UUID


class MenuItemDetailOut(MenuItemOut):
    """"MenuItem detail view shows which Recipe(s)/components it's built
    from" (locked AC) — each linked recipe's current version, so the
    detail view doesn't need a second round-trip per recipe."""

    recipes: list[RecipeDetailOut]


class EquipmentItemIssueHistoryOut(BaseModel):
    equipment_item: EquipmentItemOut
    issues: list[EquipmentIssueOut]


class SearchResultOut(BaseModel):
    result_type: str
    entity_id: uuid.UUID
    title: str
    matched_text: str
