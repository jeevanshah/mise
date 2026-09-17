"""
Epic 6 — Quick Capture (typed, rule-based).

A chef types free text; app/services/capture_classifier.py scans it with a
rule-based (not ML) classifier — keyword patterns plus a difflib fuzzy
match against Ingredient/MenuItem/EquipmentItem names — and this row
stores what it found, BEFORE anything else is touched. Nothing about a
Capture auto-creates a MenuAvailabilityEvent, PurchaseOrderLine, or
EquipmentIssue; that only happens when a chef explicitly confirms it
(app/services/capture_service.py::confirm_capture), which is also where
the "who/when/what was proposed/what was decided" log lives — on this row
(status/decided_by/decided_at) AND as a general AuditEvent.

matched_entity_type/matched_entity_id/capture_type are set together by the
classifier ONLY when there is a single, confident match. Below the
confidence threshold, or when several candidates are plausible, capture_type
is "unparsed" and matched_entity_id stays null — candidate_matches then
holds the plausible options (non-empty only in the "several plausible
matches" case; empty when there simply wasn't a good match at all), and the
chef resolves it explicitly at confirm time. This is what makes "multiple
plausible matches force a chef choice, never a silent best-guess" and "no
auto-action below threshold — falls back to an unparsed note" the same
code path with one extra piece of information, rather than two.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class CaptureType(str, PyEnum):
    restock = "restock"  # covers both "low stock" and "order" AC language —
    # both confirm to the exact same action (Epic 5's add/merge line).
    eighty_six = "eighty_six"
    equipment_issue = "equipment_issue"
    unparsed = "unparsed"


class MatchedEntityType(str, PyEnum):
    ingredient = "ingredient"
    menu_item = "menu_item"
    equipment_item = "equipment_item"


class CaptureStatus(str, PyEnum):
    proposed = "proposed"
    confirmed = "confirmed"
    rejected = "rejected"


class Capture(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "captures"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    service_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_days.id"), nullable=False, index=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    capture_type: Mapped[CaptureType] = mapped_column(
        SAEnum(CaptureType, name="capture_type"), nullable=False
    )
    matched_entity_type: Mapped[MatchedEntityType | None] = mapped_column(
        SAEnum(MatchedEntityType, name="matched_entity_type"), nullable=True
    )
    matched_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    extracted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    extracted_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Top fuzzy-match score, 0.000-1.000 — stored for transparency/debugging,
    # not itself shown as a hard requirement of any AC.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    # [{"entity_type": "ingredient", "entity_id": "...", "name": "...", "score": 0.71}, ...]
    # populated only when classification found several plausible candidates
    # and needs the chef to pick one — see module docstring.
    candidate_matches: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[CaptureStatus] = mapped_column(
        SAEnum(CaptureStatus, name="capture_status"), nullable=False, default=CaptureStatus.proposed
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Epic 7 — same sanctioned "late entry" override as PrepTask.added_after_close.
    added_after_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
