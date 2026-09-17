"""
Epic 5 — Supplier Orders.

See the locked spec's "Corrected schema primitives" block for the full AC
this implements. The single most important rule: a draft PurchaseOrder's
identity is (venue_id, supplier_id, required_delivery_date, order_cycle,
status=draft) — NOT supplier alone. Adding a line for the same ingredient
against that exact key merges into the existing line; a different delivery
date/cycle for the same supplier is a SEPARATE draft, never merged into an
existing one. See app/services/supplier_order_service.py for the
find-or-create-draft + merge-line logic that enforces this.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class PurchaseOrderStatus(str, PyEnum):
    draft = "draft"
    sending = "sending"
    sent = "sent"
    send_failed = "send_failed"


class DeliveryStatus(str, PyEnum):
    pending = "pending"
    received = "received"
    partially_received = "partially_received"


class DeliveryIssueType(str, PyEnum):
    short_delivery = "short_delivery"
    damaged = "damaged"
    wrong_item = "wrong_item"
    late = "late"
    quality = "quality"
    other = "other"


class PurchaseOrder(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False, index=True
    )

    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SAEnum(PurchaseOrderStatus, name="purchase_order_status"),
        nullable=False,
        default=PurchaseOrderStatus.draft,
    )

    # Open-draft identity, together with venue_id/supplier_id/status=draft.
    # Both nullable so either a one-off date or a standing cycle label can
    # anchor the identity; a caller must supply at least one (enforced in
    # the service layer, not here, so a raw admin insert isn't blocked by
    # a DB constraint that later needs relaxing for some edge case).
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_cycle: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Generated on first send attempt, reused on every retry of THIS order —
    # never regenerated — so a provider-side timeout can be retried without
    # risking two supplier emails for the same order.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # "Sent" means the provider accepted the message — never proof the
    # supplier received or read it. provider_message_id is the provider's
    # own id for the accepted send; recipient_snapshot is the address the
    # message actually went to, captured at send time (Supplier.contact_email
    # may change later — this column is deliberately NOT a live pointer to
    # it, so history stays accurate even if the supplier's contact changes).
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_snapshot: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        SAEnum(DeliveryStatus, name="delivery_status"),
        nullable=False,
        default=DeliveryStatus.pending,
    )

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.created_at",
    )
    delivery_issues: Mapped[list["DeliveryIssue"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="DeliveryIssue.created_at",
    )


class PurchaseOrderLine(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    # Set only on a partial delivery (AC: "partial requires a line-level
    # note") — recorded per-line since a partial delivery can under-deliver
    # different lines for different reasons.
    delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Epic 11 — "manual" (a chef built this line themselves) or "capture"
    # (Quick Capture's restock branch added it). Set once, at line
    # creation, and never touched again — a later merge that tops up an
    # existing line does NOT change who originally created it, the same
    # "a flag only ever means one specific thing" precision as
    # added_after_close elsewhere in this codebase. send_purchase_order
    # aggregates every line's source into the purchase_order.sent
    # AuditEvent (locked AC: "logged with source, manual vs. from Capture").
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class DeliveryIssue(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "delivery_issues"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    issue_type: Mapped[DeliveryIssueType] = mapped_column(
        SAEnum(DeliveryIssueType, name="delivery_issue_type"), nullable=False
    )
    # Stub photo field for v1 — a URL/path string, no upload pipeline yet.
    evidence: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="delivery_issues")
