"""
End-to-end HTTP test of the Epic 1 step 4 auth flow: request a magic link,
verify it for an access token, and use that token to call a protected
endpoint. Exercises the real app (app.main.app) through FastAPI's
TestClient, not just the service functions directly.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models.membership import Membership, MembershipRole
from app.models.organisation import Organisation
from app.models.user import User
from app.models.venue import Venue

client = TestClient(app)


def test_full_magic_link_login_flow(session):  # noqa: ARG001 — ensures DB is clean/truncated after
    request_resp = client.post("/auth/request-link", json={"email": "owner@example.com"})
    assert request_resp.status_code == 200
    dev_token = request_resp.json()["dev_token"]
    assert dev_token  # non-production default surfaces it for testability

    verify_resp = client.post("/auth/verify", json={"token": dev_token})
    assert verify_resp.status_code == 200
    access_token = verify_resp.json()["access_token"]
    assert access_token

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == "owner@example.com"
    assert body["memberships"] == []


def test_verify_rejects_unknown_token(session):  # noqa: ARG001
    resp = client.post("/auth/verify", json={"token": "totally-made-up"})
    assert resp.status_code == 400


def test_verify_rejects_reused_token(session):  # noqa: ARG001
    request_resp = client.post("/auth/request-link", json={"email": "owner2@example.com"})
    dev_token = request_resp.json()["dev_token"]

    first = client.post("/auth/verify", json={"token": dev_token})
    assert first.status_code == 200

    second = client.post("/auth/verify", json={"token": dev_token})
    assert second.status_code == 400


def test_me_requires_authentication(session):  # noqa: ARG001
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_rejects_garbage_bearer_token(session):  # noqa: ARG001
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_request_link_rejects_malformed_email(session):  # noqa: ARG001
    resp = client.post("/auth/request-link", json={"email": "not-an-email"})
    assert resp.status_code == 422


def test_me_reflects_real_memberships(session):
    """/me's memberships list must actually serialize ORM Membership rows
    (venue_id, role) correctly — the earlier flow test only exercises the
    empty-list case, which would pass even if from_attributes conversion
    were silently broken."""
    org = Organisation(name="Test Co")
    session.add(org)
    session.flush()
    venue = Venue(organisation_id=org.id, name="Test Venue")
    session.add(venue)
    session.flush()

    dev_token = client.post(
        "/auth/request-link", json={"email": "chef-with-membership@example.com"}
    ).json()["dev_token"]
    access_token = client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]

    user = session.query(User).filter_by(email="chef-with-membership@example.com").one()
    session.add(Membership(user_id=user.id, venue_id=venue.id, role=MembershipRole.head_chef))
    session.commit()

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["memberships"] == [
        {"venue_id": str(venue.id), "role": "head_chef"}
    ]
