from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class PrepTaskStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"
    blocked = "blocked"


class PrepTemplate(UUIDPKMixin, TimestampMixin, Base):
    """A reusable, ordered {station, item, quantity, priority} list (Epic 4).
    Applying it to a ServiceDay COPIES its items into fresh PrepTasks —
    later edits to a PrepTask, or to the template itself, never touch the
    other (locked AC)."""

    __tablename__ = "prep_templates"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    items: Mapped[list["PrepTemplateItem"]] = relationship(
        back_populates="template", order_by="PrepTemplateItem.sort_order"
    )


class PrepTemplateItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "prep_template_items"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prep_templates.id"), nullable=False, index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False, index=True
    )
    item: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template: Mapped["PrepTemplate"] = relationship(back_populates="items")


class PrepTask(UUIDPKMixin, TimestampMixin, Base):
    """
    Created either by applying a PrepTemplate to a ServiceDay (fields
    copied from the PrepTemplateItem, not referenced live) or by carry-
    forward from a prior day's not-done task.

    carried_to_task_id being non-null IS "marked as carried" (locked AC) —
    there's no separate status value for it, since a task can be blocked/
    in_progress/etc. right up until the day closes and it gets carried.
    carry_count is the "day-count badge": 0 for a task that was never
    carried, N+1 for a task carried forward from a task with count N — so
    it climbs by exactly one per day, never resets, and carry_forward is
    idempotent (skips a task that already has a carried_to_task_id) so
    re-running it never produces a second copy for the same day.
    """

    __tablename__ = "prep_tasks"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    service_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=False, index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False, index=True
    )
    item: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[PrepTaskStatus] = mapped_column(
        Enum(PrepTaskStatus, name="prep_task_status"), nullable=False, default=PrepTaskStatus.not_started
    )

    template_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prep_template_items.id"), nullable=True, index=True
    )
    carried_from_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prep_tasks.id"), nullable=True, index=True
    )
    carried_to_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prep_tasks.id"), nullable=True, index=True
    )
    carry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
