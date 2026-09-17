from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.service_day import ServiceDayStatus


class ServiceDayOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    business_date: date
    status: ServiceDayStatus
    opened_at: datetime | None
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class StartServiceDayRequest(BaseModel):
    business_date: date | None = None
