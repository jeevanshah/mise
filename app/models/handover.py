"""
Epic 7 — Handover. "Close day" (app/services/handover_service.py::close_service_day)
creates one Handover per ServiceDay and populates HandoverItem rows for
everything the closing chef should see: not-done PrepTasks, that day's
MenuAvailabilityEvents, currently-open EquipmentIssues, currently-open
DeliveryIssues, draft/sent PurchaseOrders, and unparsed Captures. Toggling
`included` never touches the referenced record — it's purely "does this
show up on the handover view", which is why HandoverItem exists as its own
row rather than a flag on each of those six tables.

HandoverItem is a polymorphic reference: exactly one of the six typed FK
columns below is non-null for any given row. Per the locked spec's
guidance, that's enforced with a real DB CHECK constraint (not just
application-layer discipline) — see __table_args__ — because that's the
version that actually catches a bug at write time instead of silently
storing a row that points at nothing or at two things at once.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Handover(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "handovers"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    # One Handover per ServiceDay — re-closing after a reopen updates this
    # SAME row (fresh items, note may be amended) rather than creating a
    # second one; see handover_service.close_service_day.
    service_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=False, unique=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # AC: "Time-to-close is measured (open -> save timestamp)" — captured
    # once, at close time, rather than recomputed later from
    # ServiceDay.opened_at/closed_at, so a later reopen+reclose cycle never
    # muddles what this particular close actually took.
    time_to_close_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    items: Mapped[list["HandoverItem"]] = relationship(
        back_populates="handover", cascade="all, delete-orphan"
    )


class HandoverItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "handover_items"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN prep_task_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN capture_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN equipment_issue_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN purchase_order_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN menu_availability_event_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN delivery_issue_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_handover_item_exactly_one_reference",
        ),
    )

    handover_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handovers.id"), nullable=False, index=True
    )
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    prep_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prep_tasks.id"), nullable=True, index=True
    )
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("captures.id"), nullable=True, index=True
    )
    equipment_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_issues.id"), nullable=True, index=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True, index=True
    )
    menu_availability_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_availability_events.id"), nullable=True, index=True
    )
    delivery_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_issues.id"), nullable=True, index=True
    )

    handover: Mapped["Handover"] = relationship(back_populates="items")

    @property
    def item_type(self) -> str:
        """Derived, not stored — which typed FK is set already says what
        this item is; a separate stored item_type column could drift from
        the FK that's actually populated."""
        for name in (
            "prep_task_id", "capture_id", "equipment_issue_id",
            "purchase_order_id", "menu_availability_event_id", "delivery_issue_id",
        ):
            if getattr(self, name) is not None:
                return name.removesuffix("_id")
        return ""  # pragma: no cover — the DB CHECK constraint makes this unreachable

    @property
    def item_id(self) -> uuid.UUID | None:
        for name in (
            "prep_task_id", "capture_id", "equipment_issue_id",
            "purchase_order_id", "menu_availability_event_id", "delivery_issue_id",
        ):
            value = getattr(self, name)
            if value is not None:
                return value
        return None  # pragma: no cover
