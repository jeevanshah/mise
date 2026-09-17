from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String
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
