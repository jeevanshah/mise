from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CloseServiceDayRequest(BaseModel):
    note: str | None = None


class ReopenServiceDayRequest(BaseModel):
    reason: str


class SetHandoverItemIncludedRequest(BaseModel):
    included: bool


class HandoverItemOut(BaseModel):
    id: uuid.UUID
    handover_id: uuid.UUID
    included: bool
    # Derived (not stored) on the model — see HandoverItem.item_type/item_id.
    item_type: str
    item_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class HandoverOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    service_day_id: uuid.UUID
    note: str | None
    closed_by: uuid.UUID
    closed_at: datetime
    time_to_close_seconds: int
    items: list[HandoverItemOut] = []

    model_config = {"from_attributes": True}
