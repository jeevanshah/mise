from __future__ import annotations

import uuid

from pydantic import BaseModel


class SentNotificationOut(BaseModel):
    action: str
    entity_type: str
    entity_id: uuid.UUID
    recipients: list[str]
    subject: str

    model_config = {"from_attributes": True}
