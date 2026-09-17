from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, model_validator

from app.models.roster import ShiftStatus, StaffResponseStatus


class ShiftCreateRequest(BaseModel):
    station_id: uuid.UUID
    staff_id: uuid.UUID
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "ShiftCreateRequest":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("start_at/end_at must include a timezone offset")
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class StaffResponseOut(BaseModel):
    id: uuid.UUID
    status: StaffResponseStatus
    responded_at: datetime | None
    responded_via: str | None

    model_config = {"from_attributes": True}


class ShiftOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    service_day_id: uuid.UUID
    station_id: uuid.UUID
    staff_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    status: ShiftStatus
    response: StaffResponseOut | None = None

    model_config = {"from_attributes": True}


class PublishResultOut(BaseModel):
    shift: ShiftOut
    # Only populated when settings.environment != "production" and a new
    # StaffLink was actually issued (a republish of an already-published
    # Shift is a no-op — see roster_service.publish_shift). Epic 10
    # replaces this with real email delivery.
    dev_staff_link_token: str | None = None


class PublishWeekRequest(BaseModel):
    week_start: date


class CopyWeekRequest(BaseModel):
    source_week_start: date
    target_week_start: date


class StaffRespondRequest(BaseModel):
    response: StaffResponseStatus

    @model_validator(mode="after")
    def _response_is_confirm_or_decline(self) -> "StaffRespondRequest":
        if self.response not in (StaffResponseStatus.confirmed, StaffResponseStatus.declined):
            raise ValueError("response must be 'confirmed' or 'declined'")
        return self


class StaffLinkShiftView(BaseModel):
    """What a signed link shows without a login — deliberately narrow
    (locked spec: "purpose-scoped: roster view/respond/check-in only,
    nothing else")."""

    shift_id: uuid.UUID
    station_id: uuid.UUID
    staff_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    shift_status: ShiftStatus
    response_status: StaffResponseStatus


class CoverageWarningOut(BaseModel):
    station_id: uuid.UUID
    coverage_rule_id: uuid.UUID
    day_of_week: int
    window_start: time
    window_end: time
    minimum_staff: int
    scheduled_staff: int
