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


def _invite(owner_token: str, venue_id: str, email: str, role: str) -> str:
    client.post(
        f"/venues/{venue_id}/invite", json={"email": email, "role": role}, headers=_auth(owner_token),
    )
    return _login(email)


def test_record_minutes_saved_over_http(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm1owner@example.com", "PM1 Co", "PM1 Diner")

    resp = client.post(
        f"/venues/{venue_id}/metrics/minutes-saved",
        json={"week_start": "2026-06-01", "minutes_saved": 45},
        headers=_auth(owner_token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["action"] == "metrics.minutes_saved_reported"
    assert body["after_data"] == {"week_start": "2026-06-01", "minutes_saved": 45}


def test_log_incident_over_http(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm2owner@example.com", "PM2 Co", "PM2 Diner")

    resp = client.post(
        f"/venues/{venue_id}/metrics/incidents",
        json={
            "business_date": "2026-06-01", "incident_type": "missed_order",
            "description": "Supplier never received the Friday order",
        },
        headers=_auth(owner_token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["action"] == "metrics.incident_logged"
    assert body["entity_type"] == "service_day"


def test_log_incident_with_unknown_type_returns_422(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm3owner@example.com", "PM3 Co", "PM3 Diner")

    resp = client.post(
        f"/venues/{venue_id}/metrics/incidents",
        json={"business_date": "2026-06-01", "incident_type": "kitchen_fire", "description": "n/a"},
        headers=_auth(owner_token),
    )

    assert resp.status_code == 422


def test_record_pilot_decision_over_http(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm4owner@example.com", "PM4 Co", "PM4 Diner")

    resp = client.post(
        f"/venues/{venue_id}/metrics/pilot-decision",
        json={"will_pay_at_proposed_price": True, "notes": "Ready to sign"},
        headers=_auth(owner_token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["action"] == "metrics.pilot_decision_recorded"
    assert body["after_data"] == {"will_pay_at_proposed_price": True, "notes": "Ready to sign"}


def test_pilot_decision_is_owner_only(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm5owner@example.com", "PM5 Co", "PM5 Diner")
    ops_manager_token = _invite(owner_token, venue_id, "pm5ops@example.com", "ops_manager")
    head_chef_token = _invite(owner_token, venue_id, "pm5chef@example.com", "head_chef")

    for token in (ops_manager_token, head_chef_token):
        resp = client.post(
            f"/venues/{venue_id}/metrics/pilot-decision",
            json={"will_pay_at_proposed_price": True},
            headers=_auth(token),
        )
        assert resp.status_code == 403


def test_minutes_saved_and_incidents_require_management_role(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm6owner@example.com", "PM6 Co", "PM6 Diner")
    line_staff_token = _invite(owner_token, venue_id, "pm6line@example.com", "line_staff")

    minutes_resp = client.post(
        f"/venues/{venue_id}/metrics/minutes-saved",
        json={"week_start": "2026-06-01", "minutes_saved": 10},
        headers=_auth(line_staff_token),
    )
    incident_resp = client.post(
        f"/venues/{venue_id}/metrics/incidents",
        json={"business_date": "2026-06-01", "incident_type": "missed_order", "description": "n/a"},
        headers=_auth(line_staff_token),
    )

    assert minutes_resp.status_code == 403
    assert incident_resp.status_code == 403


def test_get_pilot_metrics_returns_all_recorded_events(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pm7owner@example.com", "PM7 Co", "PM7 Diner")
    client.post(
        f"/venues/{venue_id}/metrics/minutes-saved",
        json={"week_start": "2026-06-01", "minutes_saved": 20},
        headers=_auth(owner_token),
    )
    client.post(
        f"/venues/{venue_id}/metrics/pilot-decision",
        json={"will_pay_at_proposed_price": False},
        headers=_auth(owner_token),
    )

    resp = client.get(f"/venues/{venue_id}/metrics", headers=_auth(owner_token))

    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert actions == ["metrics.minutes_saved_reported", "metrics.pilot_decision_recorded"]


def test_get_pilot_metrics_is_venue_scoped(session):  # noqa: ARG001
    owner_a_token, venue_a_id = _signup("pm8ownerA@example.com", "PM8A Co", "PM8A Diner")
    _owner_b_token, venue_b_id = _signup("pm8ownerB@example.com", "PM8B Co", "PM8B Diner")

    cross_tenant = client.get(f"/venues/{venue_b_id}/metrics", headers=_auth(owner_a_token))
    assert cross_tenant.status_code == 403
