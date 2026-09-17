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


def _station(token, venue_id, name="Grill"):
    return client.post(f"/venues/{venue_id}/stations", json={"name": name}, headers=_auth(token)).json()["id"]


def _staff(token, venue_id, name="Alex"):
    return client.post(f"/venues/{venue_id}/staff", json={"name": name}, headers=_auth(token)).json()["id"]


def _shift(token, venue_id, station_id, staff_id, start_at, end_at):
    return client.post(
        f"/venues/{venue_id}/shifts",
        json={"station_id": station_id, "staff_id": staff_id, "start_at": start_at, "end_at": end_at},
        headers=_auth(token),
    ).json()


def test_chef_brief_defaults_to_current_day_and_aggregates(session):  # noqa: ARG001
    token, venue_id = _signup("cb1owner@example.com", "CB1 Co", "CB1 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    _shift(
        token, venue_id, station_id, staff_id,
        "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00",
    )

    resp = client.get(f"/venues/{venue_id}/chef-brief", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert "service_day_id" in body
    assert "business_date" in body
    for key in (
        "rostered_staff", "coverage_gaps", "priority_open_prep_tasks",
        "approaching_order_cutoffs", "open_equipment_issues", "carried_forward_tasks",
        "unavailable_or_low_menu_items",
    ):
        assert key in body
    assert body["yesterdays_handover"] is None


def test_chef_brief_accepts_explicit_business_date_and_shows_rostered_staff(session):  # noqa: ARG001
    token, venue_id = _signup("cb2owner@example.com", "CB2 Co", "CB2 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id, "Alex")
    _shift(
        token, venue_id, station_id, staff_id,
        "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00",
    )

    resp = client.get(f"/venues/{venue_id}/chef-brief?business_date=2026-06-01", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["business_date"] == "2026-06-01"
    assert len(body["rostered_staff"]) == 1
    assert body["rostered_staff"][0]["staff_name"] == "Alex"
    assert body["rostered_staff"][0]["attendance_status"] is None


def test_chef_brief_surfaces_yesterdays_handover(session):  # noqa: ARG001
    token, venue_id = _signup("cb3owner@example.com", "CB3 Co", "CB3 Diner")
    client.post(
        f"/venues/{venue_id}/service-days/start", json={"business_date": "2026-06-01"}, headers=_auth(token)
    )
    close_resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/close", json={"note": "quiet night"}, headers=_auth(token)
    )
    assert close_resp.status_code == 200

    resp = client.get(f"/venues/{venue_id}/chef-brief?business_date=2026-06-02", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["yesterdays_handover"] is not None
    assert body["yesterdays_handover"]["note"] == "quiet night"


def test_chef_brief_any_membership_can_open_it_and_logs_an_audit_event(session):  # noqa: ARG001
    owner_token, venue_id = _signup("cb4owner@example.com", "CB4 Co", "CB4 Diner")

    client.post(
        f"/venues/{venue_id}/invite", json={"email": "cb4line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("cb4line@example.com")

    resp = client.get(f"/venues/{venue_id}/chef-brief", headers=_auth(line_token))
    assert resp.status_code == 200


def test_chef_brief_is_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("cb5ownerA@example.com", "CB5A Co", "CB5A Diner")
    token_b, venue_b_id = _signup("cb5ownerB@example.com", "CB5B Co", "CB5B Diner")

    resp = client.get(f"/venues/{venue_b_id}/chef-brief", headers=_auth(token_a))
    assert resp.status_code == 403
