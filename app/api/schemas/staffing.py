from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, Field, model_validator


class StationCreateRequest(BaseModel):
    name: str


class StationOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class StaffCreateRequest(BaseModel):
    name: str
    user_id: uuid.UUID | None = None
    contact_email: str | None = None


class StaffOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str
    user_id: uuid.UUID | None
    contact_email: str | None = None

    model_config = {"from_attributes": True}


class StaffSkillCreateRequest(BaseModel):
    station_id: uuid.UUID
    trained: bool = True


class StaffSkillOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    station_id: uuid.UUID
    trained: bool

    model_config = {"from_attributes": True}


class StaffDetailOut(StaffOut):
    skills: list[StaffSkillOut] = []


class CoverageRuleCreateRequest(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Monday .. 6=Sunday")
    window_start: time
    window_end: time
    minimum_staff: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "CoverageRuleCreateRequest":
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        return self


class CoverageRuleOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    station_id: uuid.UUID
    day_of_week: int
    window_start: time
    window_end: time
    minimum_staff: int

    model_config = {"from_attributes": True}
