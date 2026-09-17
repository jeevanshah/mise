from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class ServiceDayStatus(str, enum.Enum):
    planned = "planned"
    open = "open"
    closed = "closed"


class ServiceDay(UUIDPKMixin, TimestampMixin, Base):
    """
    business_date is derived from Venue.timezone + Venue.business_day_boundary
    by application logic when a ServiceDay is first referenced (a Shift, a
    PrepTemplate application, a scheduled notification) — NOT only when a
    user opens the app, and NOT the raw calendar date. See
    app/services/service_day_service.py for the resolution + lazy-creation
    logic (Epic 1 step 8, alongside the audit helper — both are "shared
    plumbing" other epics build on).

    planned -> open is triggered by the first operational write against this
    ServiceDay OR an explicit "Start day" action, whichever happens first.
    That transition is idempotent (calling it again once open is a no-op)
    and writes an AuditEvent — see app/services/service_day_service.py.
    open -> closed happens in the Handover epic (Epic 7), not here.
    """

    __tablename__ = "service_days"
    __table_args__ = (
        UniqueConstraint("venue_id", "business_date", name="uq_service_day_venue_date"),
    )

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ServiceDayStatus] = mapped_column(
        Enum(ServiceDayStatus, name="service_day_status"),
        nullable=False,
        default=ServiceDayStatus.planned,
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
