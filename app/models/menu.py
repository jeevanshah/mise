from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
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


class MenuAvailabilityStatus(str, enum.Enum):
    available = "available"
    low = "low"
    unavailable = "unavailable"


class MenuAvailabilityEvent(UUIDPKMixin, TimestampMixin, Base):
    """
    Epic 6 — Quick Capture. An 86/low-stock/back-in-stock call is logged
    per ServiceDay, never as a permanent flag on MenuItem — a MenuItem
    86'd today is available again tomorrow with no separate action. Like
    AttendanceEvent, this is a log: "current availability" for a MenuItem
    on a ServiceDay is a derived read (the latest event by recorded_at),
    not a column anywhere.
    """

    __tablename__ = "menu_availability_events"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id"), nullable=False, index=True
    )
    service_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=False, index=True
    )
    status: Mapped[MenuAvailabilityStatus] = mapped_column(
        Enum(MenuAvailabilityStatus, name="menu_availability_status"), nullable=False
    )
    quantity_remaining: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
