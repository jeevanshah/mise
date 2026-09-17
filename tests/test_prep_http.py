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


def test_create_template_add_items_and_apply(session):  # noqa: ARG001
    token, venue_id = _signup("p1owner@example.com", "P1 Co", "P1 Diner")
    station_id = _station(token, venue_id)

    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "Weekday"}, headers=_auth(token)
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "Dice onions", "quantity": "5", "unit": "kg", "priority": 1},
        headers=_auth(token),
    )
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "Roast chicken", "quantity": "20", "unit": "kg", "priority": 2},
        headers=_auth(token),
    )

    detail = client.get(f"/venues/{venue_id}/prep-templates/{template_id}", headers=_auth(token))
    assert [i["item"] for i in detail.json()["items"]] == ["Dice onions", "Roast chicken"]

    apply_resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )
    assert apply_resp.status_code == 200
    tasks = apply_resp.json()
    assert len(tasks) == 2
    assert all(t["status"] == "not_started" for t in tasks)


def test_prep_tasks_empty_when_no_service_day_yet(session):  # noqa: ARG001
    token, venue_id = _signup("p2owner@example.com", "P2 Co", "P2 Diner")
    resp = client.get(f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_printable_list_omits_internal_fields(session):  # noqa: ARG001
    token, venue_id = _signup("p3owner@example.com", "P3 Co", "P3 Diner")
    station_id = _station(token, venue_id, "Salad")
    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "T"}, headers=_auth(token)
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "Wash lettuce", "quantity": "2", "unit": "kg"},
        headers=_auth(token),
    )
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )

    resp = client.get(f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/printable", headers=_auth(token))
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["station_name"] == "Salad"
    assert row["item"] == "Wash lettuce"
    assert "template_item_id" not in row
    assert "carried_from_task_id" not in row


def test_only_head_chef_or_sous_chef_can_update_status(session):  # noqa: ARG001
    owner_token, venue_id = _signup("p4owner@example.com", "P4 Co", "P4 Diner")
    station_id = _station(owner_token, venue_id)
    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "T"}, headers=_auth(owner_token)
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "X", "quantity": "1", "unit": "kg"},
        headers=_auth(owner_token),
    )
    task_id = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(owner_token),
    ).json()[0]["id"]

    # owner is NOT in PREP_EXECUTION_ROLES
    owner_attempt = client.patch(
        f"/venues/{venue_id}/prep-tasks/{task_id}/status", json={"status": "done"}, headers=_auth(owner_token)
    )
    assert owner_attempt.status_code == 403

    client.post(
        f"/venues/{venue_id}/invite", json={"email": "p4sous@example.com", "role": "sous_chef"},
        headers=_auth(owner_token),
    )
    sous_token = _login("p4sous@example.com")
    sous_attempt = client.patch(
        f"/venues/{venue_id}/prep-tasks/{task_id}/status", json={"status": "done"}, headers=_auth(sous_token)
    )
    assert sous_attempt.status_code == 200
    assert sous_attempt.json()["status"] == "done"


def test_carry_forward_endpoint(session):  # noqa: ARG001
    token, venue_id = _signup("p5owner@example.com", "P5 Co", "P5 Diner")
    station_id = _station(token, venue_id)
    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "T"}, headers=_auth(token)
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "X", "quantity": "1", "unit": "kg"},
        headers=_auth(token),
    )
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )

    resp = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/carry-forward",
        json={"to_business_date": "2026-06-02"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    carried = resp.json()
    assert len(carried) == 1
    assert carried[0]["carry_count"] == 1

    next_day_tasks = client.get(
        f"/venues/{venue_id}/service-days/2026-06-02/prep-tasks", headers=_auth(token)
    ).json()
    assert len(next_day_tasks) == 1


def test_prep_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("p6ownerA@example.com", "P6A Co", "P6A Diner")
    token_b, venue_b_id = _signup("p6ownerB@example.com", "P6B Co", "P6B Diner")

    assert client.get(
        f"/venues/{venue_b_id}/prep-templates", headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/prep-templates", json={"name": "Hack"}, headers=_auth(token_a)
    ).status_code == 403
