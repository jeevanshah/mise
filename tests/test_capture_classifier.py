from decimal import Decimal

from app.models.capture import CaptureType, MatchedEntityType
from app.models.user import User
from app.services.capture_classifier import classify_capture
from app.services.catalog_service import create_equipment_item, create_ingredient, create_menu_item
from app.services.onboarding_service import create_organisation_with_venue


def _owner_venue(session):
    owner = User(email="owner@example.com")
    session.add(owner)
    session.commit()
    _, venue, _ = create_organisation_with_venue(
        session, owner=owner, organisation_name="Test Co", venue_name="Test Diner"
    )
    return owner, venue


def test_confident_ingredient_match_proposes_restock(session):
    owner, venue = _owner_venue(session)
    onions = create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")

    result = classify_capture(session, venue=venue, raw_text="running low on yellow onions, need 10kg")

    assert result.capture_type == CaptureType.restock
    assert result.matched_entity_type == MatchedEntityType.ingredient
    assert result.matched_entity_id == onions.id
    assert result.extracted_quantity == Decimal("10")
    assert result.extracted_unit == "kg"
    assert result.candidate_matches == []


def test_confident_menu_item_match_proposes_eighty_six(session):
    owner, venue = _owner_venue(session)
    salmon = create_menu_item(session, venue=venue, actor=owner, name="Grilled Salmon")

    result = classify_capture(session, venue=venue, raw_text="86 the grilled salmon")

    assert result.capture_type == CaptureType.eighty_six
    assert result.matched_entity_type == MatchedEntityType.menu_item
    assert result.matched_entity_id == salmon.id
    # "86" here is chef shorthand for "discontinue", never a quantity of 86.
    assert result.extracted_quantity is None


def test_bare_86_is_not_mistaken_for_a_quantity_but_a_real_one_still_extracts(session):
    owner, venue = _owner_venue(session)
    create_menu_item(session, venue=venue, actor=owner, name="Scallops")

    bare = classify_capture(session, venue=venue, raw_text="86 the scallops, none left")
    assert bare.extracted_quantity is None

    with_unit = classify_capture(session, venue=venue, raw_text="86 kg of scallops arrived damaged")
    assert with_unit.extracted_quantity == Decimal("86")
    assert with_unit.extracted_unit == "kg"


def test_confident_equipment_match_proposes_equipment_issue(session):
    owner, venue = _owner_venue(session)
    mixer = create_equipment_item(session, venue=venue, actor=owner, name="Stand Mixer")

    result = classify_capture(session, venue=venue, raw_text="the stand mixer is broken again")

    assert result.capture_type == CaptureType.equipment_issue
    assert result.matched_entity_type == MatchedEntityType.equipment_item
    assert result.matched_entity_id == mixer.id


def test_no_plausible_match_is_unparsed_with_no_candidates(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Yellow Onions", unit="kg", ordering_unit="sack")

    result = classify_capture(session, venue=venue, raw_text="the walk-in fridge door sticks a bit")

    assert result.capture_type == CaptureType.unparsed
    assert result.matched_entity_type is None
    assert result.candidate_matches == []


def test_multiple_plausible_matches_forces_a_choice(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Salmon Fillet", unit="kg", ordering_unit="box")
    create_menu_item(session, venue=venue, actor=owner, name="Salmon Fillet")

    result = classify_capture(session, venue=venue, raw_text="salmon fillet")

    assert result.capture_type == CaptureType.unparsed
    assert result.matched_entity_id is None
    assert len(result.candidate_matches) == 2
    entity_types = {c["entity_type"] for c in result.candidate_matches}
    assert entity_types == {"ingredient", "menu_item"}


def test_quantity_extraction_with_and_without_unit(session):
    owner, venue = _owner_venue(session)
    create_ingredient(session, venue=venue, actor=owner, name="Carrots", unit="kg", ordering_unit="bag")

    with_unit = classify_capture(session, venue=venue, raw_text="need 5kg carrots")
    assert with_unit.extracted_quantity == Decimal("5")
    assert with_unit.extracted_unit == "kg"

    no_unit = classify_capture(session, venue=venue, raw_text="need 3 carrots")
    assert no_unit.extracted_quantity == Decimal("3")
    assert no_unit.extracted_unit is None

    no_number = classify_capture(session, venue=venue, raw_text="carrots running low")
    assert no_number.extracted_quantity is None
