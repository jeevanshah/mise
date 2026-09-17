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


def _menu_item(token, venue_id, name="Grilled Salmon"):
    return client.post(
        f"/venues/{venue_id}/menu-items", json={"name": name}, headers=_auth(token)
    ).json()["id"]


def _equipment_item(token, venue_id, name="Stand Mixer"):
    return client.post(
        f"/venues/{venue_id}/equipment-items", json={"name": name}, headers=_auth(token)
    ).json()["id"]


def _ingredient(token, venue_id, name="Yellow Onions", preferred_supplier_id=None):
    body = {"name": name, "unit": "kg", "ordering_unit": "sack"}
    if preferred_supplier_id:
        body["preferred_supplier_id"] = preferred_supplier_id
    return client.post(f"/venues/{venue_id}/ingredients", json=body, headers=_auth(token)).json()["id"]


def _supplier(token, venue_id, name="Fresh Co"):
    return client.post(
        f"/venues/{venue_id}/suppliers", json={"name": name, "contact_email": "orders@fresh.co"},
        headers=_auth(token),
    ).json()["id"]


def test_create_capture_proposes_eighty_six(session):  # noqa: ARG001
    token, venue_id = _signup("cap1owner@example.com", "Cap1 Co", "Cap1 Diner")
    _menu_item(token, venue_id)

    resp = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "86 the grilled salmon"}, headers=_auth(token)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["capture_type"] == "eighty_six"
    assert body["status"] == "proposed"
    assert body["matched_entity_type"] == "menu_item"


def test_confirm_eighty_six_creates_menu_availability_event(session):  # noqa: ARG001
    token, venue_id = _signup("cap2owner@example.com", "Cap2 Co", "Cap2 Diner")
    _menu_item(token, venue_id)
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "86 the grilled salmon"}, headers=_auth(token)
    ).json()

    resp = client.post(f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_type"] == "menu_availability_event"
    assert body["capture"]["status"] == "confirmed"


def test_confirm_restock_creates_purchase_order_line(session):  # noqa: ARG001
    token, venue_id = _signup("cap3owner@example.com", "Cap3 Co", "Cap3 Diner")
    supplier_id = _supplier(token, venue_id)
    _ingredient(token, venue_id, preferred_supplier_id=supplier_id)
    capture = client.post(
        f"/venues/{venue_id}/captures",
        json={"raw_text": "running low on yellow onions, need 10kg"}, headers=_auth(token),
    ).json()
    assert capture["capture_type"] == "restock"

    resp = client.post(
        f"/venues/{venue_id}/captures/{capture['id']}/confirm",
        json={"required_delivery_date": "2026-06-10"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["result_type"] == "purchase_order"


def test_unparsed_capture_requires_manual_resolution(session):  # noqa: ARG001
    token, venue_id = _signup("cap4owner@example.com", "Cap4 Co", "Cap4 Diner")
    equipment_id = _equipment_item(token, venue_id, "Combi Oven")
    capture = client.post(
        f"/venues/{venue_id}/captures",
        json={"raw_text": "something in the kitchen needs attention"}, headers=_auth(token),
    ).json()
    assert capture["capture_type"] == "unparsed"

    no_resolution = client.post(
        f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(token)
    )
    assert no_resolution.status_code == 422

    resolved = client.post(
        f"/venues/{venue_id}/captures/{capture['id']}/confirm",
        json={"entity_type": "equipment_item", "entity_id": equipment_id},
        headers=_auth(token),
    )
    assert resolved.status_code == 200
    assert resolved.json()["result_type"] == "equipment_issue"


def test_reject_capture(session):  # noqa: ARG001
    token, venue_id = _signup("cap5owner@example.com", "Cap5 Co", "Cap5 Diner")
    _menu_item(token, venue_id)
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "86 the grilled salmon"}, headers=_auth(token)
    ).json()

    resp = client.post(
        f"/venues/{venue_id}/captures/{capture['id']}/reject",
        json={"reason": "not needed"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    again = client.post(f"/venues/{venue_id}/captures/{capture['id']}/reject", json={}, headers=_auth(token))
    assert again.status_code == 409


def test_list_captures_filters_by_status(session):  # noqa: ARG001
    token, venue_id = _signup("cap6owner@example.com", "Cap6 Co", "Cap6 Diner")
    _menu_item(token, venue_id)
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "86 the grilled salmon"}, headers=_auth(token)
    ).json()
    client.post(f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(token))
    client.post(f"/venues/{venue_id}/captures", json={"raw_text": "another 86 note"}, headers=_auth(token))

    all_captures = client.get(f"/venues/{venue_id}/captures", headers=_auth(token)).json()
    assert len(all_captures) == 2

    confirmed_only = client.get(f"/venues/{venue_id}/captures?capture_status=confirmed", headers=_auth(token)).json()
    assert len(confirmed_only) == 1


def test_capture_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("cap7ownerA@example.com", "Cap7A Co", "Cap7A Diner")
    token_b, venue_b_id = _signup("cap7ownerB@example.com", "Cap7B Co", "Cap7B Diner")

    assert client.get(f"/venues/{venue_b_id}/captures", headers=_auth(token_a)).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/captures", json={"raw_text": "test"}, headers=_auth(token_a)
    ).status_code == 403


def test_only_management_roles_can_confirm(session):  # noqa: ARG001
    owner_token, venue_id = _signup("cap8owner@example.com", "Cap8 Co", "Cap8 Diner")
    _menu_item(owner_token, venue_id)
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "86 the grilled salmon"}, headers=_auth(owner_token)
    ).json()

    client.post(
        f"/venues/{venue_id}/invite", json={"email": "cap8line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("cap8line@example.com")

    # line_staff CAN create a capture (kitchen-floor visibility)...
    create_resp = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "another one"}, headers=_auth(line_token)
    )
    assert create_resp.status_code == 201

    # ...but cannot confirm/reject the decision.
    confirm_resp = client.post(
        f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(line_token)
    )
    assert confirm_resp.status_code == 403
