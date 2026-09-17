from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.attendance import AttendanceSource, AttendanceStatus


class AttendanceEventCreateRequest(BaseModel):
    status: AttendanceStatus
    note: str | None = None


class AttendanceEventOut(BaseModel):
    id: uuid.UUID
    shift_id: uuid.UUID
    status: AttendanceStatus
    source: AttendanceSource
    actor_user_id: uuid.UUID | None
    note: str | None
    recorded_at: datetime

    model_config = {"from_attributes": True}


class CurrentAttendanceOut(BaseModel):
    shift_id: uuid.UUID
    # None means "expected" — no AttendanceEvent has been logged yet.
    status: AttendanceStatus | None
