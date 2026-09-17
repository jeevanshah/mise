from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str) -> str:
    dev_token = client.post("/auth/request-link", json={"email": email}).json()["dev_token"]
    return client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]


def _signup(email: str, org_name: str, venue_name: str) -> tuple[str, str]:
    token = _login(email)
    venue_id = client.post(
        "/organisations", json={"organisation_name": org_name, "venue_name": venue_name},
        headers=_auth(token),
    ).json()["venue"]["id"]
    return token, venue_id


def test_get_current_service_day_lazily_creates_it(session):  # noqa: ARG001
    token, venue_id = _signup("sd1owner@example.com", "SD1 Co", "SD1 Diner")

    resp = client.get(f"/venues/{venue_id}/service-days/current", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "planned"

    # calling again returns the SAME service day, not a duplicate
    resp2 = client.get(f"/venues/{venue_id}/service-days/current", headers=_auth(token))
    assert resp2.json()["id"] == resp.json()["id"]


def test_start_service_day_opens_it_and_is_idempotent(session):  # noqa: ARG001
    token, venue_id = _signup("sd2owner@example.com", "SD2 Co", "SD2 Diner")

    resp = client.post(
        f"/venues/{venue_id}/service-days/start", json={"business_date": "2026-06-01"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    assert resp.json()["opened_at"] is not None

    resp2 = client.post(
        f"/venues/{venue_id}/service-days/start", json={"business_date": "2026-06-01"}, headers=_auth(token)
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == resp.json()["id"]


def test_start_service_day_defaults_to_today(session):  # noqa: ARG001
    token, venue_id = _signup("sd3owner@example.com", "SD3 Co", "SD3 Diner")
    resp = client.post(f"/venues/{venue_id}/service-days/start", json={}, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"


def test_line_staff_cannot_start_service_day_but_can_view_current(session):  # noqa: ARG001
    owner_token, venue_id = _signup("sd4owner@example.com", "SD4 Co", "SD4 Diner")
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "sd4line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("sd4line@example.com")

    assert client.post(
        f"/venues/{venue_id}/service-days/start", json={}, headers=_auth(line_token)
    ).status_code == 403
    assert client.get(
        f"/venues/{venue_id}/service-days/current", headers=_auth(line_token)
    ).status_code == 200


def test_service_days_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("sd5ownerA@example.com", "SD5A Co", "SD5A Diner")
    token_b, venue_b_id = _signup("sd5ownerB@example.com", "SD5B Co", "SD5B Diner")

    assert client.get(
        f"/venues/{venue_b_id}/service-days/current", headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/service-days/start", json={}, headers=_auth(token_a)
    ).status_code == 403
