from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class MembershipRole(str, enum.Enum):
    owner = "owner"
    ops_manager = "ops_manager"
    head_chef = "head_chef"
    sous_chef = "sous_chef"
    line_staff = "line_staff"


class Membership(UUIDPKMixin, TimestampMixin, Base):
    """A User's role and access scope for one Venue. Permission enforcement
    (role -> allowed actions per venue) reads from this table via
    app/api/deps.py::require_membership — a Membership is looked up fresh on
    every request, never cached in a token, so a role change or removal
    takes effect immediately rather than waiting for a JWT to expire."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "venue_id", name="uq_membership_user_venue"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, name="membership_role"), nullable=False
    )
