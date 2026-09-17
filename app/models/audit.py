from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import utcnow


class AuditEvent(Base):
    """
    Append-only. NEVER updated or deleted by application code.

    Must be written in the SAME database transaction as the mutation it
    records (see app/services/audit_service.py::audited_transaction) — if
    either the mutation or this row fails to commit, neither does. A
    business-data change with no audit record (or an audit record for a
    change that never actually committed) is exactly the bug this table
    exists to prevent, so it must never be written via a separate
    session/commit from the thing it's auditing.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    service_day_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(120), nullable=False)       # e.g. "shift.published"
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)   # e.g. "shift"
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)     # stringified UUID/id

    before_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
