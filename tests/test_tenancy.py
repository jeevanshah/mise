"""
Epic 1 step 9 (cross-venue tenancy tests).

Two halves, both covered here:

1. Data-layer: every operational table is scoped by venue_id, and a
   venue_id-filtered query never returns another venue's rows. Proves the
   SCHEMA supports isolation.
2. HTTP-layer (added once Epic 1 step 4 — auth/Membership — existed): a
   validly authenticated request with a Membership at Venue A is refused
   when it addresses Venue B via a venue-scoped route, through the real
   app.api.deps.require_membership dependency and a real signed access
   token — not just a direct query, an actual request through the ASGI
   stack. This is what proves enforcement, not just schema shape.
"""

import uuid
from datetime import date

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_membership
from app.core.database import get_session
from app.models.membership import Membership, MembershipRole
from app.models.organisation import Organisation
from app.models.service_day import ServiceDay
from app.models.staff import Staff
from app.models.supplier import Supplier
from app.models.user import User
from app.models.venue import Venue
from app.services.auth_service import create_access_token


def _make_org_and_venue(session, name: str) -> Venue:
    org = Organisation(name=f"{name} Org")
    session.add(org)
    session.flush()
    venue = Venue(organisation_id=org.id, name=f"{name} Venue")
    session.add(venue)
    session.flush()
    return venue


def test_staff_query_scoped_to_venue_excludes_other_venues(session):
    venue_a = _make_org_and_venue(session, "A")
    venue_b = _make_org_and_venue(session, "B")

    session.add_all(
        [
            Staff(venue_id=venue_a.id, name="Alice (Venue A)"),
            Staff(venue_id=venue_a.id, name="Amir (Venue A)"),
            Staff(venue_id=venue_b.id, name="Bao (Venue B)"),
        ]
    )
    session.commit()

    venue_a_staff = session.query(Staff).filter_by(venue_id=venue_a.id).all()
    venue_b_staff = session.query(Staff).filter_by(venue_id=venue_b.id).all()

    assert {s.name for s in venue_a_staff} == {"Alice (Venue A)", "Amir (Venue A)"}
    assert {s.name for s in venue_b_staff} == {"Bao (Venue B)"}
    assert len(venue_a_staff) + len(venue_b_staff) == 3


def test_supplier_scoped_to_venue_excludes_other_venues(session):
    venue_a = _make_org_and_venue(session, "A")
    venue_b = _make_org_and_venue(session, "B")

    session.add_all(
        [
            Supplier(venue_id=venue_a.id, name="Farm Fresh (A's supplier)"),
            Supplier(venue_id=venue_b.id, name="Ocean Co (B's supplier)"),
        ]
    )
    session.commit()

    venue_a_suppliers = session.query(Supplier).filter_by(venue_id=venue_a.id).all()
    assert len(venue_a_suppliers) == 1
    assert venue_a_suppliers[0].name == "Farm Fresh (A's supplier)"


def test_service_day_unique_constraint_is_per_venue_not_global(session):
    """Two different venues can both have a ServiceDay for the same
    business_date — the UNIQUE constraint is (venue_id, business_date), not
    business_date alone. This would fail loudly if someone "simplified" the
    constraint later."""
    venue_a = _make_org_and_venue(session, "A")
    venue_b = _make_org_and_venue(session, "B")
    same_date = date(2026, 12, 25)

    session.add_all(
        [
            ServiceDay(venue_id=venue_a.id, business_date=same_date),
            ServiceDay(venue_id=venue_b.id, business_date=same_date),
        ]
    )
    session.commit()  # must not raise a unique-constraint violation

    assert session.query(ServiceDay).filter_by(business_date=same_date).count() == 2


def test_service_day_unique_constraint_blocks_duplicate_within_same_venue(session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    venue = _make_org_and_venue(session, "C")
    same_date = date(2026, 12, 25)

    session.add(ServiceDay(venue_id=venue.id, business_date=same_date))
    session.commit()

    session.add(ServiceDay(venue_id=venue.id, business_date=same_date))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- HTTP-level half (Epic 1 step 4 dependency) ---------------------------


def _build_test_app_with_secret_route(session) -> FastAPI:
    """A throwaway FastAPI app — NOT app.main.app — mounting one venue-scoped
    route behind the real require_membership dependency. Keeps this purely
    a test of the auth/permission machinery, without adding a permanent
    stub business endpoint to the shipped API (real venue-scoped endpoints
    arrive in Epic 1 steps 5-7)."""
    test_app = FastAPI()

    @test_app.get("/venues/{venue_id}/secret")
    def read_secret(
        venue_id: uuid.UUID, membership: Membership = Depends(require_membership())
    ) -> dict:
        return {"role": membership.role.value}

    test_app.dependency_overrides[get_session] = lambda: session
    return test_app


def test_membership_at_venue_a_is_refused_at_venue_b_over_http(session):
    venue_a = _make_org_and_venue(session, "A-http")
    venue_b = _make_org_and_venue(session, "B-http")

    user = User(email="chef-http@example.com")
    session.add(user)
    session.flush()
    session.add(Membership(user_id=user.id, venue_id=venue_a.id, role=MembershipRole.head_chef))
    session.commit()

    token = create_access_token(user.id)
    client = TestClient(_build_test_app_with_secret_route(session))
    headers = {"Authorization": f"Bearer {token}"}

    allowed = client.get(f"/venues/{venue_a.id}/secret", headers=headers)
    assert allowed.status_code == 200
    assert allowed.json() == {"role": "head_chef"}

    denied = client.get(f"/venues/{venue_b.id}/secret", headers=headers)
    assert denied.status_code == 403


def test_venue_scoped_route_requires_authentication_over_http(session):
    venue = _make_org_and_venue(session, "NoAuth-http")
    client = TestClient(_build_test_app_with_secret_route(session))

    resp = client.get(f"/venues/{venue.id}/secret")
    assert resp.status_code == 401


def test_venue_scoped_route_403s_a_nonexistent_venue_same_as_someone_elses(session):
    """A Membership-less request to a venue that doesn't exist at all must
    read identically (403) to one that exists but belongs to someone else —
    never a 404, which would leak which venue IDs are real across tenants."""
    real_venue = _make_org_and_venue(session, "Real-http")
    user = User(email="no-membership@example.com")
    session.add(user)
    session.commit()

    token = create_access_token(user.id)
    client = TestClient(_build_test_app_with_secret_route(session))
    headers = {"Authorization": f"Bearer {token}"}

    made_up_venue_id = uuid.uuid4()
    resp_fake = client.get(f"/venues/{made_up_venue_id}/secret", headers=headers)
    resp_real_but_unowned = client.get(f"/venues/{real_venue.id}/secret", headers=headers)

    assert resp_fake.status_code == 403
    assert resp_real_but_unowned.status_code == 403
