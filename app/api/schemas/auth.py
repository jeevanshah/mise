from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr

from app.models.membership import MembershipRole


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkRequestResponse(BaseModel):
    detail: str
    # Only populated when settings.environment != "production" — see
    # app/api/routes/auth.py. Epic 10 replaces this with real email delivery.
    dev_token: str | None = None


class MagicLinkVerifyRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    venue_id: uuid.UUID
    role: MembershipRole

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    memberships: list[MembershipOut]
