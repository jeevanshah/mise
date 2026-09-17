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


def _start_day(token, venue_id, business_date="2026-06-01"):
    resp = client.post(
        f"/venues/{venue_id}/service-days/start", json={"business_date": business_date}, headers=_auth(token)
    )
    assert resp.status_code == 200
    return resp.json()


def _station(token, venue_id, name="Grill"):
    return client.post(f"/venues/{venue_id}/stations", json={"name": name}, headers=_auth(token)).json()["id"]


def _template_with_item(token, venue_id, station_id, item="Dice onions"):
    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "T"}, headers=_auth(token)
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": item, "quantity": "1", "unit": "kg"},
        headers=_auth(token),
    )
    return template_id


def test_close_day_requires_open_service_day(session):  # noqa: ARG001
    token, venue_id = _signup("h1owner@example.com", "H1 Co", "H1 Diner")

    resp = client.post(f"/venues/{venue_id}/service-days/2026-06-01/close", json={}, headers=_auth(token))
    assert resp.status_code == 404  # never referenced, so no ServiceDay row exists yet


def test_close_day_populates_handover_and_returns_it(session):  # noqa: ARG001
    token, venue_id = _signup("h2owner@example.com", "H2 Co", "H2 Diner")
    _start_day(token, venue_id)
    station_id = _station(token, venue_id)
    template_id = _template_with_item(token, venue_id, station_id)
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )

    resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/close", json={"note": "quiet night"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["note"] == "quiet night"
    assert len(body["items"]) == 1
    assert body["items"][0]["item_type"] == "prep_task"
    assert body["items"][0]["included"] is True

    # ServiceDay is now closed: applying the template again (without the
    # late-entry override) is rejected.
    again = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )
    assert again.status_code == 409


def test_apply_template_after_close_with_override_succeeds(session):  # noqa: ARG001
    token, venue_id = _signup("h3owner@example.com", "H3 Co", "H3 Diner")
    _start_day(token, venue_id)
    station_id = _station(token, venue_id)
    template_id = _template_with_item(token, venue_id, station_id)
    client.post(f"/venues/{venue_id}/service-days/2026-06-01/close", json={}, headers=_auth(token))

    resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id, "added_after_close": True}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()[0]["added_after_close"] is True


def test_get_handover_404s_before_close(session):  # noqa: ARG001
    token, venue_id = _signup("h4owner@example.com", "H4 Co", "H4 Diner")
    _start_day(token, venue_id)

    resp = client.get(f"/venues/{venue_id}/service-days/2026-06-01/handover", headers=_auth(token))
    assert resp.status_code == 404


def test_reopen_then_get_handover_and_toggle_included(session):  # noqa: ARG001
    token, venue_id = _signup("h5owner@example.com", "H5 Co", "H5 Diner")
    _start_day(token, venue_id)
    station_id = _station(token, venue_id)
    template_id = _template_with_item(token, venue_id, station_id)
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )
    close_resp = client.post(f"/venues/{venue_id}/service-days/2026-06-01/close", json={}, headers=_auth(token))
    item_id = close_resp.json()["items"][0]["id"]

    reopen_resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/reopen", json={"reason": "forgot something"},
        headers=_auth(token),
    )
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["status"] == "open"

    # Reopening again is rejected (not closed).
    again = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/reopen", json={"reason": "again"}, headers=_auth(token)
    )
    assert again.status_code == 409

    toggle_resp = client.patch(
        f"/venues/{venue_id}/handover-items/{item_id}/included", json={"included": False}, headers=_auth(token)
    )
    assert toggle_resp.status_code == 200
    toggled_item = next(i for i in toggle_resp.json()["items"] if i["id"] == item_id)
    assert toggled_item["included"] is False

    fetched = client.get(f"/venues/{venue_id}/service-days/2026-06-01/handover", headers=_auth(token))
    assert fetched.status_code == 200


def test_only_management_roles_can_close_or_reopen(session):  # noqa: ARG001
    owner_token, venue_id = _signup("h6owner@example.com", "H6 Co", "H6 Diner")
    _start_day(owner_token, venue_id)

    client.post(
        f"/venues/{venue_id}/invite", json={"email": "h6line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("h6line@example.com")

    close_resp = client.post(f"/venues/{venue_id}/service-days/2026-06-01/close", json={}, headers=_auth(line_token))
    assert close_resp.status_code == 403


def test_handover_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("h7ownerA@example.com", "H7A Co", "H7A Diner")
    token_b, venue_b_id = _signup("h7ownerB@example.com", "H7B Co", "H7B Diner")
    _start_day(token_a, venue_a_id)
    client.post(f"/venues/{venue_a_id}/service-days/2026-06-01/close", json={}, headers=_auth(token_a))

    resp = client.get(f"/venues/{venue_b_id}/service-days/2026-06-01/handover", headers=_auth(token_a))
    assert resp.status_code == 403


def test_capture_late_entry_override_against_closed_day(session):  # noqa: ARG001
    token, venue_id = _signup("h8owner@example.com", "H8 Co", "H8 Diner")
    _start_day(token, venue_id)
    client.post(
        f"/venues/{venue_id}/menu-items", json={"name": "Grilled Salmon"}, headers=_auth(token)
    )
    client.post(f"/venues/{venue_id}/service-days/2026-06-01/close", json={}, headers=_auth(token))

    rejected = client.post(
        f"/venues/{venue_id}/captures",
        json={"raw_text": "86 the grilled salmon", "business_date": "2026-06-01"}, headers=_auth(token),
    )
    assert rejected.status_code == 409

    accepted = client.post(
        f"/venues/{venue_id}/captures",
        json={"raw_text": "86 the grilled salmon", "business_date": "2026-06-01", "added_after_close": True},
        headers=_auth(token),
    )
    assert accepted.status_code == 201
    assert accepted.json()["added_after_close"] is True
