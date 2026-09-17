"""
Proves the specific claim from the locked spec: an AuditEvent is committed
in the SAME transaction as the mutation it records — if either fails,
neither is committed.
"""

from app.models.audit import AuditEvent
from app.models.organisation import Organisation
from app.models.venue import Venue
from app.services.audit_service import audited_transaction


def _make_org_and_venue(session):
    org = Organisation(name="Test Co")
    session.add(org)
    session.flush()
    venue = Venue(organisation_id=org.id, name="Test Venue")
    session.add(venue)
    session.flush()
    session.commit()
    return org, venue


def test_mutation_and_audit_event_commit_together(session):
    org, venue = _make_org_and_venue(session)

    with audited_transaction(session, organisation_id=org.id, venue_id=venue.id) as audit:
        venue.name = "Renamed Venue"
        session.add(venue)
        audit.record(
            action="venue.renamed",
            entity_type="venue",
            entity_id=venue.id,
            before={"name": "Test Venue"},
            after={"name": "Renamed Venue"},
        )

    session.expire_all()
    refreshed_venue = session.get(Venue, venue.id)
    assert refreshed_venue.name == "Renamed Venue"

    events = session.query(AuditEvent).filter_by(entity_id=str(venue.id)).all()
    assert len(events) == 1
    assert events[0].action == "venue.renamed"
    assert events[0].after_data == {"name": "Renamed Venue"}


def test_failure_inside_block_rolls_back_both_mutation_and_audit(session):
    org, venue = _make_org_and_venue(session)
    original_name = venue.name

    class DeliberateFailure(Exception):
        pass

    try:
        with audited_transaction(session, organisation_id=org.id, venue_id=venue.id) as audit:
            venue.name = "Should Not Stick"
            session.add(venue)
            audit.record(
                action="venue.renamed",
                entity_type="venue",
                entity_id=venue.id,
                before={"name": original_name},
                after={"name": "Should Not Stick"},
            )
            # Simulate a failure AFTER both the mutation and the audit record
            # have been staged on the session, but before commit — this is
            # exactly the case the atomicity requirement exists to cover.
            raise DeliberateFailure("simulated failure before commit")
    except DeliberateFailure:
        pass

    session.expire_all()
    refreshed_venue = session.get(Venue, venue.id)
    assert refreshed_venue.name == original_name, (
        "mutation must not persist if the transaction block raised"
    )

    events = session.query(AuditEvent).filter_by(entity_id=str(venue.id)).all()
    assert len(events) == 0, (
        "no orphan AuditEvent should exist for a mutation that never committed"
    )


def test_audit_event_can_carry_no_before_data_for_a_creation(session):
    org, venue = _make_org_and_venue(session)

    with audited_transaction(session, organisation_id=org.id, venue_id=venue.id) as audit:
        audit.record(
            action="venue.created",
            entity_type="venue",
            entity_id=venue.id,
            before=None,
            after={"name": venue.name},
        )

    event = session.query(AuditEvent).filter_by(action="venue.created").one()
    assert event.before_data is None
    assert event.after_data == {"name": venue.name}
