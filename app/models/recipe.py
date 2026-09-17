from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Recipe(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "recipes"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class RecipeVersion(UUIDPKMixin, TimestampMixin, Base):
    """Editing a Recipe creates a new version; old versions stay viewable —
    nothing is ever overwritten in place (Epic 9 relies on this for history)."""

    __tablename__ = "recipe_versions"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version_no", name="uq_recipe_version_number"),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    yield_qty: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    yield_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecipeIngredient(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "recipe_ingredients"

    recipe_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipe_versions.id"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)


class MenuItemRecipe(Base):
    """Join table: which Recipe(s)/components a MenuItem is built from.
    Plain association table (no surrogate id needed) — a MenuItem<->Recipe
    pair is either linked or it isn't."""

    __tablename__ = "menu_item_recipes"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), primary_key=True
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id"), primary_key=True
    )
