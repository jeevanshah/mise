from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    """
    Auth identity — deliberately minimal. No password hash: login is
    magic-link only (see app/models/magic_link.py, app/services/auth_service.py).
    A User existing does NOT imply a Staff record, and vice versa (see
    Staff.user_id — nullable, on purpose).
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
