from __future__ import annotations

import uuid
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organisation import Organisation


class Venue(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "venues"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # IANA timezone name, e.g. "Australia/Sydney". Combined with
    # business_day_boundary this defines a venue's business_date —
    # NOT the same thing as the calendar date. A Friday dinner service
    # ending at 1am Saturday is still business_date = Friday, because
    # 1am falls before the boundary hour.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Australia/Sydney")

    # Hours before this time-of-day belong to the PRIOR business date.
    # Default 04:00 — chosen because no hospitality venue's "day" reasonably
    # ends before then; override per venue if their close is later/earlier.
    business_day_boundary: Mapped[time] = mapped_column(Time, nullable=False, default=time(4, 0))

    organisation: Mapped["Organisation"] = relationship(back_populates="venues")
