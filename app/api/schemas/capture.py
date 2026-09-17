from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.capture import CaptureStatus, CaptureType, MatchedEntityType
from app.models.equipment import EquipmentIssuePriority
from app.models.menu import MenuAvailabilityStatus


class CreateCaptureRequest(BaseModel):
    raw_text: str


class CaptureOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    service_day_id: uuid.UUID
    raw_text: str
    capture_type: CaptureType
    matched_entity_type: MatchedEntityType | None
    matched_entity_id: uuid.UUID | None
    extracted_quantity: Decimal | None
    extracted_unit: str | None
    confidence: Decimal | None
    candidate_matches: list[dict] | None
    status: CaptureStatus
    decided_by: uuid.UUID | None
    decided_at: datetime | None

    model_config = {"from_attributes": True}


class ConfirmCaptureRequest(BaseModel):
    # Required only when the capture has no confident classifier match
    # (capture_type == unparsed) — otherwise defaults to what was proposed.
    entity_type: MatchedEntityType | None = None
    entity_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    unit: str | None = None

    # restock only
    supplier_id: uuid.UUID | None = None
    required_delivery_date: date | None = None
    order_cycle: str | None = None

    # eighty_six only
    availability_status: MenuAvailabilityStatus = MenuAvailabilityStatus.unavailable
    quantity_remaining: Decimal | None = None

    # equipment_issue only
    priority: EquipmentIssuePriority = EquipmentIssuePriority.medium
    photos: str | None = None


class RejectCaptureRequest(BaseModel):
    reason: str | None = None


class ConfirmCaptureResult(BaseModel):
    capture: CaptureOut
    result_type: str
    result_id: uuid.UUID
