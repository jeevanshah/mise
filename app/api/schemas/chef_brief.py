from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas.handover import HandoverOut
from app.api.schemas.prep import PrepTaskOut
from app.models.equipment import EquipmentIssuePriority, EquipmentIssueStatus
from app.models.menu import MenuAvailabilityStatus


class RosteredStaffStatusOut(BaseModel):
    shift_id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    station_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    # null = "expected" — no AttendanceEvent logged yet.
    attendance_status: str | None

    model_config = {"from_attributes": True}


class CoverageGapOut(BaseModel):
    station_id: uuid.UUID
    coverage_rule_id: uuid.UUID
    day_of_week: int
    window_start: time
    window_end: time
    minimum_staff: int
    scheduled_staff: int

    model_config = {"from_attributes": True}


class ApproachingCutoffOut(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    purchase_order_id: uuid.UUID
    cutoff_at: datetime

    model_config = {"from_attributes": True}


class EquipmentIssueOut(BaseModel):
    id: uuid.UUID
    equipment_item_id: uuid.UUID
    priority: EquipmentIssuePriority
    status: EquipmentIssueStatus
    photos: str | None
    resolution_notes: str | None
    opened_at: datetime

    model_config = {"from_attributes": True}


class MenuItemAvailabilityOut(BaseModel):
    menu_item_id: uuid.UUID
    menu_item_name: str
    status: MenuAvailabilityStatus
    quantity_remaining: Decimal | None
    recorded_at: datetime

    model_config = {"from_attributes": True}


class ChefBriefOut(BaseModel):
    service_day_id: uuid.UUID
    business_date: date
    rostered_staff: list[RosteredStaffStatusOut]
    coverage_gaps: list[CoverageGapOut]
    priority_open_prep_tasks: list[PrepTaskOut]
    approaching_order_cutoffs: list[ApproachingCutoffOut]
    open_equipment_issues: list[EquipmentIssueOut]
    yesterdays_handover: HandoverOut | None
    carried_forward_tasks: list[PrepTaskOut]
    unavailable_or_low_menu_items: list[MenuItemAvailabilityOut]

    model_config = {"from_attributes": True}
