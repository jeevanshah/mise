from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, EmailStr

from app.models.equipment import EquipmentStatus


class SupplierCreateRequest(BaseModel):
    name: str
    contact_email: EmailStr | None = None
    order_days: str | None = None
    cutoff_time: time | None = None


class SupplierOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str
    contact_email: str | None
    order_days: str | None
    cutoff_time: time | None

    model_config = {"from_attributes": True}


class IngredientCreateRequest(BaseModel):
    name: str
    unit: str
    ordering_unit: str
    preferred_supplier_id: uuid.UUID | None = None


class IngredientOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str
    unit: str
    ordering_unit: str
    preferred_supplier_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class MenuItemCreateRequest(BaseModel):
    name: str


class MenuItemOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class EquipmentItemCreateRequest(BaseModel):
    name: str
    location: str | None = None
    repair_contact: str | None = None


class EquipmentItemOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str
    location: str | None
    repair_contact: str | None
    status: EquipmentStatus

    model_config = {"from_attributes": True}
