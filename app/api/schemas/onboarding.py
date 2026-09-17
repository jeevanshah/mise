from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, EmailStr, model_validator

from app.models.membership import MembershipRole


class OrganisationOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class VenueOut(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    timezone: str
    business_day_boundary: time

    model_config = {"from_attributes": True}


class OrganisationCreateRequest(BaseModel):
    organisation_name: str
    venue_name: str
    timezone: str | None = None
    business_day_boundary: time | None = None


class MembershipSummary(BaseModel):
    venue_id: uuid.UUID
    role: MembershipRole

    model_config = {"from_attributes": True}


class OrganisationCreateResponse(BaseModel):
    organisation: OrganisationOut
    venue: VenueOut
    membership: MembershipSummary


class VenueUpdateRequest(BaseModel):
    timezone: str | None = None
    business_day_boundary: time | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "VenueUpdateRequest":
        if self.timezone is None and self.business_day_boundary is None:
            raise ValueError("Provide at least one of timezone or business_day_boundary")
        return self


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: MembershipRole


class InviteUserResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    venue_id: uuid.UUID
    role: MembershipRole
