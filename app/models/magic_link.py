from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class MagicLink(UUIDPKMixin, TimestampMixin, Base):
    """
    A single-use, expiring login token for a User (Epic 1 step 4).

    Follows the same security pattern the locked spec mandates for staff
    signed links (Epic 2): the raw token is emailed/returned to the caller
    once and never stored — only `token_hash` (sha256) lives in the DB, so a
    leaked database dump can't be used to log in as anyone. `consumed_at`
    enforces single-use; `expires_at` bounds the exposure window.

    No email-sending exists yet (that's Epic 10, Operational Email
    Notifications) — see app/api/routes/auth.py for how the raw token is
    surfaced in the interim.
    """

    __tablename__ = "magic_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="login")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
