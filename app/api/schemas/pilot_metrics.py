from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class MinutesSavedRequest(BaseModel):
    week_start: date
    minutes_saved: int


class LogIncidentRequest(BaseModel):
    business_date: date
    incident_type: str
    description: str


class PilotDecisionRequest(BaseModel):
    will_pay_at_proposed_price: bool
    notes: str | None = None


class PilotMetricEventOut(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    after_data: dict | None
    recorded_at: datetime

    model_config = {"from_attributes": True}
