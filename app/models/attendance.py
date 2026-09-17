from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class AttendanceStatus(str, enum.Enum):
    present = "present"
    late = "late"
    absent = "absent"
    sick = "sick"


class AttendanceSource(str, enum.Enum):
    chef = "chef"
    staff_link = "staff_link"


class AttendanceEvent(UUIDPKMixin, TimestampMixin, Base):
    """
    Epic 3 — an immutable, append-only log, never an overwritten row (same
    reasoning as AuditEvent). "Attendance state" for a Shift is a derived
    read — the latest AttendanceEvent by recorded_at — not a column
    anywhere; see app/services/attendance_service.py::get_current_status.
    No event yet means "expected", which is likewise never stored.

    Deliberately NO location/GPS/biometric field anywhere on this model —
    called out explicitly in the locked spec, not an oversight to "add
    later". A chef event and a staff_link event are just two rows; the
    later one (by recorded_at) wins for display, but neither is ever
    mutated or deleted — see the AttendanceEvent history endpoint for the
    full record.
    """

    __tablename__ = "attendance_events"

    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False, index=True
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status"), nullable=False
    )
    source: Mapped[AttendanceSource] = mapped_column(
        Enum(AttendanceSource, name="attendance_source"), nullable=False
    )
    # Set only for source=chef — a staff_link check-in has no logged-in actor.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
