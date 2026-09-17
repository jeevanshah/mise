from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from app.models.purchase_order import DeliveryIssueType, DeliveryStatus, PurchaseOrderStatus


class AddOrMergeLineRequest(BaseModel):
    supplier_id: uuid.UUID
    ingredient_id: uuid.UUID
    quantity: Decimal
    unit: str | None = None
    required_delivery_date: date | None = None
    order_cycle: str | None = None

    @model_validator(mode="after")
    def _require_identity(self) -> "AddOrMergeLineRequest":
        if self.required_delivery_date is None and self.order_cycle is None:
            raise ValueError("Provide required_delivery_date or order_cycle")
        return self


class UpdateLineQuantityRequest(BaseModel):
    quantity: Decimal


class PurchaseOrderLineOut(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    quantity: Decimal
    unit: str
    delivery_note: str | None
    source: str

    model_config = {"from_attributes": True}


class DeliveryIssueOut(BaseModel):
    id: uuid.UUID
    issue_type: DeliveryIssueType
    evidence: str | None
    resolution: str | None

    model_config = {"from_attributes": True}


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    supplier_id: uuid.UUID
    status: PurchaseOrderStatus
    required_delivery_date: date | None
    order_cycle: str | None
    idempotency_key: str | None
    sent_at: datetime | None
    sent_by: uuid.UUID | None
    provider_message_id: str | None
    recipient_snapshot: str | None
    last_error: str | None
    delivery_status: DeliveryStatus
    lines: list[PurchaseOrderLineOut]
    delivery_issues: list[DeliveryIssueOut]

    model_config = {"from_attributes": True}


class MarkDeliveryRequest(BaseModel):
    partial: bool
    line_notes: dict[uuid.UUID, str] | None = None


class LogDeliveryIssueRequest(BaseModel):
    issue_type: DeliveryIssueType
    evidence: str | None = None
    resolution: str | None = None
