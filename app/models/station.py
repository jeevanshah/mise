from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy import ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class Station(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "stations"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class StationCoverageRule(UUIDPKMixin, TimestampMixin, Base):
    """Minimum staff required for a Station within a day-of-week + time
    window. A daily minimum with no window would let one short morning
    shift count as "coverage" for the whole day — the window is what makes
    the rule mean something. service_type/ServicePeriod is deliberately NOT
    a column here for v1 (open question, pending customer confirmation) —
    add it as a nullable FK later if the answer is yes; nothing here breaks."""

    __tablename__ = "station_coverage_rules"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "day_of_week", "window_start", "window_end",
            name="uq_coverage_rule_station_day_window",
        ),
    )

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False, index=True
    )
    # 0 = Monday .. 6 = Sunday (Python's date.weekday() convention — pick one
    # and be consistent at the API boundary, this is the one the app uses).
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[time] = mapped_column(Time, nullable=False)
    window_end: Mapped[time] = mapped_column(Time, nullable=False)
    minimum_staff: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
