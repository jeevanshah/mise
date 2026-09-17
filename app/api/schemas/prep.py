from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.prep import PrepTaskStatus


class PrepTemplateCreateRequest(BaseModel):
    name: str


class PrepTemplateOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class PrepTemplateItemCreateRequest(BaseModel):
    station_id: uuid.UUID
    item: str
    quantity: Decimal = Field(gt=0)
    unit: str
    priority: int = 0


class PrepTemplateItemOut(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    station_id: uuid.UUID
    item: str
    quantity: Decimal
    unit: str
    priority: int
    sort_order: int

    model_config = {"from_attributes": True}


class PrepTemplateDetailOut(PrepTemplateOut):
    items: list[PrepTemplateItemOut] = []


class ApplyPrepTemplateRequest(BaseModel):
    template_id: uuid.UUID
    added_after_close: bool = False


class PrepTaskOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    service_day_id: uuid.UUID
    station_id: uuid.UUID
    item: str
    quantity: Decimal
    unit: str
    priority: int
    status: PrepTaskStatus
    template_item_id: uuid.UUID | None
    carried_from_task_id: uuid.UUID | None
    carried_to_task_id: uuid.UUID | None
    carry_count: int
    added_after_close: bool

    model_config = {"from_attributes": True}


class PrepTaskStatusUpdateRequest(BaseModel):
    status: PrepTaskStatus


class PrintablePrepTaskOut(BaseModel):
    """No chef-only chrome (locked AC) — just what belongs on a printed
    prep list, plus the station name so it doesn't need a second lookup."""

    station_id: uuid.UUID
    station_name: str
    item: str
    quantity: Decimal
    unit: str
    priority: int
    status: PrepTaskStatus


class CarryForwardRequest(BaseModel):
    to_business_date: date
