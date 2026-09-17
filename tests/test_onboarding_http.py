"""
End-to-end HTTP tests for Epic 1 step 5 (Org/Venue onboarding endpoints),
built on top of the real auth flow (step 4) — no shortcuts that bypass
login, so this also doubles as a real-endpoint tenancy check (see the
bottom of this file) alongside the throwaway-route version in
tests/test_tenancy.py.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _signup(email: str) -> str:
    """Full magic-link login for a brand-new email, returns a bearer token."""
    dev_token = client.post("/auth/request-link", json={"email": email}).json()["dev_token"]
    return client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_signup_creates_org_and_venue_with_owner_membership(session):  # noqa: ARG001
    token = _signup("newowner@example.com")

    resp = client.post(
        "/organisations",
        json={"organisation_name": "Test Co", "venue_name": "Test Diner"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["organisation"]["name"] == "Test Co"
    assert body["venue"]["name"] == "Test Diner"
    assert body["venue"]["timezone"] == "Australia/Sydney"
    assert body["venue"]["business_day_boundary"] == "04:00:00"
    assert body["membership"]["role"] == "owner"
    assert body["membership"]["venue_id"] == body["venue"]["id"]

    me = client.get("/auth/me", headers=_auth(token)).json()
    assert me["memberships"] == [{"venue_id": body["venue"]["id"], "role": "owner"}]


def test_signup_requires_authentication(session):  # noqa: ARG001
    resp = client.post(
        "/organisations", json={"organisation_name": "Test Co", "venue_name": "Test Diner"}
    )
    assert resp.status_code == 401


def test_get_venue_requires_membership(session):  # noqa: ARG001
    owner_token = _signup("owner2@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co2", "venue_name": "Diner2"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]

    outsider_token = _signup("outsider@example.com")
    resp = client.get(f"/venues/{venue_id}", headers=_auth(outsider_token))
    assert resp.status_code == 403

    resp_owner = client.get(f"/venues/{venue_id}", headers=_auth(owner_token))
    assert resp_owner.status_code == 200
    assert resp_owner.json()["id"] == venue_id


def test_owner_can_update_venue_settings(session):  # noqa: ARG001
    token = _signup("owner3@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co3", "venue_name": "Diner3"},
        headers=_auth(token),
    ).json()["venue"]["id"]

    resp = client.patch(
        f"/venues/{venue_id}",
        json={"business_day_boundary": "03:30:00"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["business_day_boundary"] == "03:30:00"
    assert resp.json()["timezone"] == "Australia/Sydney"  # untouched field preserved


def test_update_venue_requires_at_least_one_field(session):  # noqa: ARG001
    token = _signup("owner4@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co4", "venue_name": "Diner4"},
        headers=_auth(token),
    ).json()["venue"]["id"]

    resp = client.patch(f"/venues/{venue_id}", json={}, headers=_auth(token))
    assert resp.status_code == 422


def test_non_owner_cannot_update_venue_settings(session):  # noqa: ARG001
    owner_token = _signup("owner5@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co5", "venue_name": "Diner5"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]

    chef_token = _signup("chef5@example.com")
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "chef5@example.com", "role": "head_chef"},
        headers=_auth(owner_token),
    )

    resp = client.patch(
        f"/venues/{venue_id}",
        json={"timezone": "Australia/Perth"},
        headers=_auth(chef_token),
    )
    assert resp.status_code == 403


def test_owner_can_invite_user_who_can_then_log_in_with_correct_role(session):  # noqa: ARG001
    owner_token = _signup("owner6@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co6", "venue_name": "Diner6"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]

    invite_resp = client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "newchef6@example.com", "role": "sous_chef"},
        headers=_auth(owner_token),
    )
    assert invite_resp.status_code == 201
    assert invite_resp.json()["role"] == "sous_chef"

    # The invited person logs in for the first time via their own magic link
    # (no account existed before the invite created it).
    chef_token = _signup("newchef6@example.com")
    me = client.get("/auth/me", headers=_auth(chef_token)).json()
    assert me["memberships"] == [{"venue_id": venue_id, "role": "sous_chef"}]

    venue_resp = client.get(f"/venues/{venue_id}", headers=_auth(chef_token))
    assert venue_resp.status_code == 200


def test_only_owner_can_invite(session):  # noqa: ARG001
    owner_token = _signup("owner7@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co7", "venue_name": "Diner7"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "souschef7@example.com", "role": "sous_chef"},
        headers=_auth(owner_token),
    )
    sous_chef_token = _signup("souschef7@example.com")

    resp = client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "another@example.com", "role": "line_staff"},
        headers=_auth(sous_chef_token),
    )
    assert resp.status_code == 403


def test_inviting_an_existing_member_again_is_rejected(session):  # noqa: ARG001
    owner_token = _signup("owner8@example.com")
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": "Co8", "venue_name": "Diner8"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "chef8@example.com", "role": "sous_chef"},
        headers=_auth(owner_token),
    )

    resp = client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "chef8@example.com", "role": "head_chef"},
        headers=_auth(owner_token),
    )
    assert resp.status_code == 409


def test_a_venue_membership_does_not_grant_access_to_an_unrelated_venue(session):  # noqa: ARG001
    """Same tenancy guarantee as test_tenancy.py, exercised through the real
    onboarding endpoints rather than a throwaway test route."""
    owner_a_token = _signup("ownerA@example.com")
    venue_a_id = client.post(
        "/organisations",
        json={"organisation_name": "CoA", "venue_name": "DinerA"},
        headers=_auth(owner_a_token),
    ).json()["venue"]["id"]

    owner_b_token = _signup("ownerB@example.com")
    venue_b_id = client.post(
        "/organisations",
        json={"organisation_name": "CoB", "venue_name": "DinerB"},
        headers=_auth(owner_b_token),
    ).json()["venue"]["id"]

    cross_read = client.get(f"/venues/{venue_b_id}", headers=_auth(owner_a_token))
    assert cross_read.status_code == 403

    cross_invite = client.post(
        f"/venues/{venue_b_id}/invite",
        json={"email": "someone@example.com", "role": "line_staff"},
        headers=_auth(owner_a_token),
    )
    assert cross_invite.status_code == 403

    cross_update = client.patch(
        f"/venues/{venue_b_id}",
        json={"timezone": "Australia/Perth"},
        headers=_auth(owner_a_token),
    )
    assert cross_update.status_code == 403
