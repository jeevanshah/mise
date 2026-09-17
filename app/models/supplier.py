from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy import ForeignKey, String, Text, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Supplier(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Comma-separated day names for v1 (e.g. "mon,thu") — a normalized table
    # is easy to split out later if the order-day rules get more complex than
    # "same days every week", which is all the known customer needs so far.
    order_days: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cutoff_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    # Epic 9 — Kitchen Memory: free text (delivery quirks, account numbers,
    # standing instructions, ...) a chef jots down for this supplier and
    # can later find via full-text search. The one column this epic adds —
    # its own AC is scoped to "no new TABLES", not "no schema changes at
    # all", and there's no existing free-text field on Supplier to search.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
