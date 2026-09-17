from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Staff(UUIDPKMixin, TimestampMixin, Base):
    """A kitchen employee record. user_id is nullable ON PURPOSE — a line
    staff member can be rostered and appear in coverage without ever having
    a login; they're reached via a signed link (Epic 2) instead."""

    __tablename__ = "staff"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class StaffSkill(UUIDPKMixin, TimestampMixin, Base):
    """Staff x Station capability. A Shift can still be assigned without one
    of these existing — the roster (Epic 2) just shows a warning icon."""

    __tablename__ = "staff_skills"
    __table_args__ = (
        UniqueConstraint("staff_id", "station_id", name="uq_staff_skill_staff_station"),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False, index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False, index=True
    )
    trained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
