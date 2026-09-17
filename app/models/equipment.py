from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class EquipmentStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class EquipmentItem(UUIDPKMixin, TimestampMixin, Base):
    """Minimal CRUD here in Epic 1 on purpose — Quick Capture (Epic 6)
    fuzzy-matches against this table, so it has to exist during onboarding.
    The polished issue-history view is Epic 9 (Kitchen Memory); EquipmentIssue
    itself is introduced in Epic 6 where it's first written to."""

    __tablename__ = "equipment_items"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    repair_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[EquipmentStatus] = mapped_column(
        Enum(EquipmentStatus, name="equipment_status"),
        nullable=False,
        default=EquipmentStatus.active,
    )


class EquipmentIssuePriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EquipmentIssueStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


class EquipmentIssue(UUIDPKMixin, TimestampMixin, Base):
    """Epic 6 — Quick Capture is what first writes to this table (see
    EquipmentItem's docstring). One EquipmentItem can accumulate several
    issues over time — the full history is Epic 9 (Kitchen Memory); this
    table is deliberately minimal here, matching EquipmentItem's own
    Epic-1-minimal-now/Epic-9-polish split."""

    __tablename__ = "equipment_issues"

    equipment_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_items.id"), nullable=False, index=True
    )
    priority: Mapped[EquipmentIssuePriority] = mapped_column(
        Enum(EquipmentIssuePriority, name="equipment_issue_priority"),
        nullable=False,
        default=EquipmentIssuePriority.medium,
    )
    status: Mapped[EquipmentIssueStatus] = mapped_column(
        Enum(EquipmentIssueStatus, name="equipment_issue_status"),
        nullable=False,
        default=EquipmentIssueStatus.open,
    )
    # Stub field, same pattern as Epic 5's DeliveryIssue.evidence — a
    # comma-separated list of URLs/paths, no upload pipeline in v1.
    photos: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
