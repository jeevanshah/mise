"""
Epic 6 — Quick Capture's rule-based (NOT machine-learning) classifier.

Pure functions, no DB writes, no session mutation — capture_service.py
calls classify_capture() and persists whatever it returns. Kept in its own
module so the matching rules can be tuned/tested in isolation from the
Capture row lifecycle.

Approach: fuzzy-match the raw text against every Ingredient/MenuItem/
EquipmentItem name at the venue using difflib (stdlib, deterministic, no
model/training — "rule-based" per the locked AC), plus a simple regex for
a leading quantity+unit. Which TABLE the winning name comes from is what
decides the proposed capture_type (Ingredient -> restock, MenuItem ->
eighty_six, EquipmentItem -> equipment_issue) — a chef typing "86 the
salmon" matches the MenuItem "Salmon" and that alone is enough to propose
eighty_six, no separate keyword dictionary to keep in sync with the catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.capture import CaptureType, MatchedEntityType
from app.models.equipment import EquipmentItem
from app.models.ingredient import Ingredient
from app.models.menu import MenuItem
from app.models.venue import Venue

# Below this score, a candidate isn't even considered "plausible" — it's
# noise, not a near-miss worth surfacing to the chef.
MIN_CANDIDATE_SCORE = Decimal("0.35")

# At/above this score, a single unambiguous candidate is auto-proposed
# without asking the chef to also confirm which entity was meant (they
# still confirm/reject the ACTION itself — this only skips the "which
# entity did you mean" step).
MATCH_CONFIDENCE_THRESHOLD = Decimal("0.6")

# Public — capture_service reuses this to turn a chef's explicit
# entity_type resolution (for an unparsed/ambiguous capture) into the same
# action type this classifier would have proposed for a confident match.
ENTITY_TYPE_TO_CAPTURE_TYPE = {
    MatchedEntityType.ingredient: CaptureType.restock,
    MatchedEntityType.menu_item: CaptureType.eighty_six,
    MatchedEntityType.equipment_item: CaptureType.equipment_issue,
}

_QUANTITY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(kg|kilograms?|g|grams?|ml|millilit(?:res?|ers?)|l|lit(?:res?|ers?)"
    r"|cases?|boxes?|units?|each|portions?|sacks?|crates?)?",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    entity_type: MatchedEntityType
    entity_id: object  # uuid.UUID
    name: str
    score: Decimal


@dataclass
class ClassificationResult:
    capture_type: CaptureType
    matched_entity_type: MatchedEntityType | None = None
    matched_entity_id: object | None = None
    extracted_quantity: Decimal | None = None
    extracted_unit: str | None = None
    confidence: Decimal | None = None
    candidate_matches: list[dict] = field(default_factory=list)


def _score(name: str, text: str) -> Decimal:
    name_l, text_l = name.lower(), text.lower()
    if name_l in text_l:
        return Decimal("1.0")
    return Decimal(str(round(SequenceMatcher(None, name_l, text_l).ratio(), 3)))


def _extract_quantity(text: str) -> tuple[Decimal | None, str | None]:
    """Skips a bare, unit-less "86" — chef shorthand for "discontinue this",
    not a quantity of 86 anything (e.g. "86 the grilled salmon" must not
    extract quantity=86). "86 kg of onions" still extracts fine since a
    unit is present. Otherwise takes the first number found."""
    for match in _QUANTITY_RE.finditer(text):
        raw_number, raw_unit = match.group(1), match.group(2)
        if raw_number == "86" and raw_unit is None:
            continue
        return Decimal(raw_number), raw_unit.lower() if raw_unit else None
    return None, None


def classify_capture(session: Session, *, venue: Venue, raw_text: str) -> ClassificationResult:
    quantity, unit = _extract_quantity(raw_text)

    candidates: list[Candidate] = []
    for ingredient in session.query(Ingredient).filter_by(venue_id=venue.id).all():
        score = _score(ingredient.name, raw_text)
        if score >= MIN_CANDIDATE_SCORE:
            candidates.append(Candidate(MatchedEntityType.ingredient, ingredient.id, ingredient.name, score))
    for menu_item in session.query(MenuItem).filter_by(venue_id=venue.id).all():
        score = _score(menu_item.name, raw_text)
        if score >= MIN_CANDIDATE_SCORE:
            candidates.append(Candidate(MatchedEntityType.menu_item, menu_item.id, menu_item.name, score))
    for equipment_item in session.query(EquipmentItem).filter_by(venue_id=venue.id).all():
        score = _score(equipment_item.name, raw_text)
        if score >= MIN_CANDIDATE_SCORE:
            candidates.append(Candidate(MatchedEntityType.equipment_item, equipment_item.id, equipment_item.name, score))

    candidates.sort(key=lambda c: c.score, reverse=True)
    strong = [c for c in candidates if c.score >= MATCH_CONFIDENCE_THRESHOLD]

    if len(strong) == 1:
        winner = strong[0]
        return ClassificationResult(
            capture_type=ENTITY_TYPE_TO_CAPTURE_TYPE[winner.entity_type],
            matched_entity_type=winner.entity_type,
            matched_entity_id=winner.entity_id,
            extracted_quantity=quantity,
            extracted_unit=unit,
            confidence=winner.score,
            candidate_matches=[],
        )

    # Either nothing cleared the bar (candidate_matches stays empty — a
    # genuine "unparsed note", the chef picks a type from scratch), or
    # several candidates plausibly did (candidate_matches lists them — the
    # chef picks one, never a silent best-guess). Both are capture_type
    # "unparsed"; this list is the only thing that tells them apart.
    plausible = strong if len(strong) > 1 else []
    return ClassificationResult(
        capture_type=CaptureType.unparsed,
        matched_entity_type=None,
        matched_entity_id=None,
        extracted_quantity=quantity,
        extracted_unit=unit,
        confidence=candidates[0].score if candidates else None,
        candidate_matches=[
            {
                "entity_type": c.entity_type.value,
                "entity_id": str(c.entity_id),
                "name": c.name,
                "score": str(c.score),
            }
            for c in plausible
        ],
    )
