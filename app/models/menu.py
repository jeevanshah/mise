from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class MenuItem(UUIDPKMixin, TimestampMixin, Base):
    """A sellable menu item. Deliberately NOT the same thing as a Recipe —
    one menu item (e.g. a burger) can be built from several Recipes/components
    (patty, sauce, bun). The link is MenuItemRecipe (see recipe.py). 86'ing a
    MenuItem is a day-scoped MenuAvailabilityEvent (Epic 6), never a column
    on this table."""

    __tablename__ = "menu_items"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
