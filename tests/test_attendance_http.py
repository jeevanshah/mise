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


def _shift(token, venue_id):
    station_id = client.post(f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(token)).json()["id"]
    staff_id = client.post(f"/venues/{venue_id}/staff", json={"name": "Alex"}, headers=_auth(token)).json()["id"]
    shift = client.post(
        f"/venues/{venue_id}/shifts",
        json={
            "station_id": station_id, "staff_id": staff_id,
            "start_at": "2026-06-01T09:00:00+10:00", "end_at": "2026-06-01T17:00:00+10:00",
        },
        headers=_auth(token),
    ).json()
    return shift["id"]


def test_chef_logs_attendance_and_current_reflects_it(session):  # noqa: ARG001
    token, venue_id = _signup("a1owner@example.com", "A1 Co", "A1 Diner")
    shift_id = _shift(token, venue_id)

    resp = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/attendance-events",
        json={"status": "present"}, headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "chef"

    current = client.get(f"/venues/{venue_id}/shifts/{shift_id}/attendance", headers=_auth(token))
    assert current.json()["status"] == "present"


def test_current_attendance_is_null_before_any_event(session):  # noqa: ARG001
    token, venue_id = _signup("a2owner@example.com", "A2 Co", "A2 Diner")
    shift_id = _shift(token, venue_id)

    current = client.get(f"/venues/{venue_id}/shifts/{shift_id}/attendance", headers=_auth(token))
    assert current.json()["status"] is None


def test_line_staff_cannot_log_attendance_as_chef(session):  # noqa: ARG001
    owner_token, venue_id = _signup("a3owner@example.com", "A3 Co", "A3 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "a3line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("a3line@example.com")
    shift_id = _shift(owner_token, venue_id)

    resp = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/attendance-events",
        json={"status": "present"}, headers=_auth(line_token),
    )
    assert resp.status_code == 403


def test_check_in_via_staff_link_and_reject_second_attempt(session):  # noqa: ARG001
    token, venue_id = _signup("a4owner@example.com", "A4 Co", "A4 Diner")
    shift_id = _shift(token, venue_id)
    link_token = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(token)
    ).json()["dev_staff_link_token"]

    first = client.post(
        f"/staff-links/{link_token}/attendance-events", json={"status": "present"}
    )
    assert first.status_code == 201
    assert first.json()["source"] == "staff_link"

    second = client.post(
        f"/staff-links/{link_token}/attendance-events", json={"status": "late"}
    )
    assert second.status_code == 409


def test_attendance_history_retains_all_events_in_order(session):  # noqa: ARG001
    token, venue_id = _signup("a5owner@example.com", "A5 Co", "A5 Diner")
    shift_id = _shift(token, venue_id)
    link_token = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(token)
    ).json()["dev_staff_link_token"]

    client.post(f"/staff-links/{link_token}/attendance-events", json={"status": "present"})
    client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/attendance-events",
        json={"status": "late", "note": "arrived after a delivery mix-up"}, headers=_auth(token),
    )

    history = client.get(f"/venues/{venue_id}/shifts/{shift_id}/attendance-events", headers=_auth(token))
    assert [e["source"] for e in history.json()] == ["staff_link", "chef"]

    current = client.get(f"/venues/{venue_id}/shifts/{shift_id}/attendance", headers=_auth(token))
    assert current.json()["status"] == "late"


def test_attendance_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("a6ownerA@example.com", "A6A Co", "A6A Diner")
    token_b, venue_b_id = _signup("a6ownerB@example.com", "A6B Co", "A6B Diner")
    shift_b_id = _shift(token_b, venue_b_id)

    assert client.post(
        f"/venues/{venue_b_id}/shifts/{shift_b_id}/attendance-events",
        json={"status": "present"}, headers=_auth(token_a),
    ).status_code == 403
    assert client.get(
        f"/venues/{venue_b_id}/shifts/{shift_b_id}/attendance", headers=_auth(token_a)
    ).status_code == 403
