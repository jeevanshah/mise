from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class ShiftStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    cancelled = "cancelled"


class StaffResponseStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    declined = "declined"


class Shift(UUIDPKMixin, TimestampMixin, Base):
    """
    Epic 2 — Kitchen Roster. One Shift = one Station x one Staff member for
    a span of time; a station/day cell with several staff is several Shift
    rows, not one row with a staff list (this is what makes the overlap
    check below a simple per-staff query).

    start_at/end_at are tz-aware INSTANTS, not a (date, time-of-day) pair —
    a dinner shift can run 18:00 to 01:00 and still needs correct overlap
    arithmetic across that midnight crossing. business_date/service_day is
    resolved from start_at the same way ServiceDay itself is (see
    app/services/service_day_service.py::resolve_business_date) — a shift
    belongs to the business day it STARTS in, even if it ends after the
    next calendar day begins.
    """

    __tablename__ = "shifts"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    service_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=False, index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id"), nullable=False, index=True
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False, index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ShiftStatus] = mapped_column(
        Enum(ShiftStatus, name="shift_status"), nullable=False, default=ShiftStatus.draft
    )

    response: Mapped["StaffResponse"] = relationship(
        back_populates="shift", uselist=False, cascade="all, delete-orphan"
    )


class StaffResponse(UUIDPKMixin, TimestampMixin, Base):
    """
    Deliberately a SEPARATE state machine from Shift.status (locked spec:
    "a cancelled Shift can have had a confirmed StaffResponse") — cancelling
    or republishing a Shift never touches this row. One row per Shift,
    created alongside it at pending, updated in place by respond_to_shift.
    """

    __tablename__ = "staff_responses"

    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False, unique=True, index=True
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False, index=True
    )
    status: Mapped[StaffResponseStatus] = mapped_column(
        Enum(StaffResponseStatus, name="staff_response_status"),
        nullable=False,
        default=StaffResponseStatus.pending,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "login" or "staff_link" — which of the two sanctioned response paths
    # was used (see the signed-link design note on StaffLink below).
    responded_via: Mapped[str | None] = mapped_column(String(20), nullable=True)

    shift: Mapped["Shift"] = relationship(back_populates="response")


class StaffLink(UUIDPKMixin, TimestampMixin, Base):
    """
    The signed link line staff use to confirm/decline a Shift without a
    login (locked spec: "staff-specific, purpose-scoped ... expiring,
    stored server-side as a hashed token ... revocable, unable to reach any
    other Staff's records even with a guessed URL, and invalidated
    automatically if the underlying Shift is cancelled").

    Scoped to exactly ONE Shift (not "all of this Staff's shifts") — each
    roster-publish notification carries its own link for its own shift,
    the same way each Epic-3 check-in notification will carry its own.
    That's what makes "invalidated if the underlying Shift is cancelled"
    a precise, checkable rule rather than a fuzzy one: is_valid() below
    checks the live Shift status, never a cached flag, same reasoning as
    require_membership re-querying the DB instead of trusting the token.

    No email provider exists yet (Epic 10) — see roster_service.publish_shift
    for how the raw token is surfaced in the interim, mirroring MagicLink's
    dev_token pattern exactly.
    """

    __tablename__ = "staff_links"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False, index=True
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
