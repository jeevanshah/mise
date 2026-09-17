from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _signup(email: str, org_name: str, venue_name: str) -> tuple[str, str]:
    dev_token = client.post("/auth/request-link", json={"email": email}).json()["dev_token"]
    token = client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]
    venue_id = client.post(
        "/organisations",
        json={"organisation_name": org_name, "venue_name": venue_name},
        headers=_auth(token),
    ).json()["venue"]["id"]
    return token, venue_id


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str) -> str:
    dev_token = client.post("/auth/request-link", json={"email": email}).json()["dev_token"]
    return client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]


def test_owner_can_create_and_list_stations(session):  # noqa: ARG001
    token, venue_id = _signup("s1owner@example.com", "S1 Co", "S1 Diner")

    resp = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(token))
    assert resp.status_code == 201
    assert resp.json()["name"] == "Grill"

    list_resp = client.get(f"/venues/{venue_id}/stations", headers=_auth(token))
    assert [s["name"] for s in list_resp.json()] == ["Grill"]


def test_line_staff_cannot_create_station(session):  # noqa: ARG001
    owner_token, venue_id = _signup("s2owner@example.com", "S2 Co", "S2 Diner")
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "s2line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("s2line@example.com")

    resp = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(line_token))
    assert resp.status_code == 403

    # but they CAN read
    resp_read = client.get(f"/venues/{venue_id}/stations", headers=_auth(line_token))
    assert resp_read.status_code == 200


def test_create_staff_without_user_id_and_fetch_detail(session):  # noqa: ARG001
    token, venue_id = _signup("s3owner@example.com", "S3 Co", "S3 Diner")

    resp = client.post(f"/venues/{venue_id}/staff", json={"name": "Line Cook"}, headers=_auth(token))
    assert resp.status_code == 201
    staff_id = resp.json()["id"]
    assert resp.json()["user_id"] is None

    detail = client.get(f"/venues/{venue_id}/staff/{staff_id}", headers=_auth(token))
    assert detail.status_code == 200
    assert detail.json()["skills"] == []


def test_create_staff_rejects_unknown_user_id(session):  # noqa: ARG001
    token, venue_id = _signup("s4owner@example.com", "S4 Co", "S4 Diner")
    fake_user_id = "00000000-0000-0000-0000-000000000000"

    resp = client.post(
        f"/venues/{venue_id}/staff", json={"name": "Ghost", "user_id": fake_user_id}, headers=_auth(token)
    )
    assert resp.status_code == 422


def test_add_staff_skill_and_reject_duplicate(session):  # noqa: ARG001
    token, venue_id = _signup("s5owner@example.com", "S5 Co", "S5 Diner")
    staff_id = client.post(f"/venues/{venue_id}/staff", json={"name": "Cook"}, headers=_auth(token)).json()["id"]
    station_id = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(token)).json()["id"]

    resp = client.post(
        f"/venues/{venue_id}/staff/{staff_id}/skills",
        json={"station_id": station_id, "trained": True},
        headers=_auth(token),
    )
    assert resp.status_code == 201

    dup = client.post(
        f"/venues/{venue_id}/staff/{staff_id}/skills",
        json={"station_id": station_id, "trained": False},
        headers=_auth(token),
    )
    assert dup.status_code == 409

    detail = client.get(f"/venues/{venue_id}/staff/{staff_id}", headers=_auth(token))
    assert len(detail.json()["skills"]) == 1


def test_coverage_rule_create_list_and_validation(session):  # noqa: ARG001
    token, venue_id = _signup("s6owner@example.com", "S6 Co", "S6 Diner")
    station_id = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(token)).json()["id"]

    good = client.post(
        f"/venues/{venue_id}/stations/{station_id}/coverage-rules",
        json={"day_of_week": 0, "window_start": "10:00:00", "window_end": "14:00:00", "minimum_staff": 2},
        headers=_auth(token),
    )
    assert good.status_code == 201

    backwards = client.post(
        f"/venues/{venue_id}/stations/{station_id}/coverage-rules",
        json={"day_of_week": 1, "window_start": "14:00:00", "window_end": "10:00:00"},
        headers=_auth(token),
    )
    assert backwards.status_code == 422

    duplicate = client.post(
        f"/venues/{venue_id}/stations/{station_id}/coverage-rules",
        json={"day_of_week": 0, "window_start": "10:00:00", "window_end": "14:00:00", "minimum_staff": 5},
        headers=_auth(token),
    )
    assert duplicate.status_code == 409

    listing = client.get(f"/venues/{venue_id}/stations/{station_id}/coverage-rules", headers=_auth(token))
    assert len(listing.json()) == 1
    assert listing.json()[0]["minimum_staff"] == 2


def test_out_of_range_day_of_week_is_rejected(session):  # noqa: ARG001
    token, venue_id = _signup("s7owner@example.com", "S7 Co", "S7 Diner")
    station_id = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(token)).json()["id"]

    resp = client.post(
        f"/venues/{venue_id}/stations/{station_id}/coverage-rules",
        json={"day_of_week": 7, "window_start": "10:00:00", "window_end": "14:00:00"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_staffing_endpoints_are_venue_scoped(session):  # noqa: ARG001
    """Epic 1 step 9: a Membership at Venue A must not reach Venue B's
    stations/staff/coverage rules through the real endpoints."""
    token_a, venue_a_id = _signup("s8ownerA@example.com", "S8A Co", "S8A Diner")
    token_b, venue_b_id = _signup("s8ownerB@example.com", "S8B Co", "S8B Diner")
    station_b_id = client.post(
        f"/venues/{venue_b_id}/stations", json={"name": "Fryer"}, headers=_auth(token_b)
    ).json()["id"]

    assert client.get(f"/venues/{venue_b_id}/stations", headers=_auth(token_a)).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/stations", json={"name": "Hack"}, headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/staff", json={"name": "Hack"}, headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/stations/{station_b_id}/coverage-rules",
        json={"day_of_week": 0, "window_start": "10:00:00", "window_end": "14:00:00"},
        headers=_auth(token_a),
    ).status_code == 403
