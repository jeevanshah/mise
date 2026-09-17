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


def test_create_and_list_supplier(session):  # noqa: ARG001
    token, venue_id = _signup("c1owner@example.com", "C1 Co", "C1 Diner")

    resp = client.post(
        f"/venues/{venue_id}/suppliers",
        json={"name": "Farm Fresh", "contact_email": "orders@farmfresh.example.com"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Farm Fresh"

    listing = client.get(f"/venues/{venue_id}/suppliers", headers=_auth(token))
    assert len(listing.json()) == 1


def test_create_ingredient_with_and_without_supplier(session):  # noqa: ARG001
    token, venue_id = _signup("c2owner@example.com", "C2 Co", "C2 Diner")
    supplier_id = client.post(
        f"/venues/{venue_id}/suppliers", json={"name": "Farm Fresh"}, headers=_auth(token)
    ).json()["id"]

    with_supplier = client.post(
        f"/venues/{venue_id}/ingredients",
        json={"name": "Tomato", "unit": "kg", "ordering_unit": "crate", "preferred_supplier_id": supplier_id},
        headers=_auth(token),
    )
    assert with_supplier.status_code == 201

    without_supplier = client.post(
        f"/venues/{venue_id}/ingredients",
        json={"name": "Salt", "unit": "g", "ordering_unit": "bag"},
        headers=_auth(token),
    )
    assert without_supplier.status_code == 201
    assert without_supplier.json()["preferred_supplier_id"] is None


def test_ingredient_rejects_cross_venue_preferred_supplier(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("c3ownerA@example.com", "C3A Co", "C3A Diner")
    token_b, venue_b_id = _signup("c3ownerB@example.com", "C3B Co", "C3B Diner")
    supplier_b_id = client.post(
        f"/venues/{venue_b_id}/suppliers", json={"name": "B's Supplier"}, headers=_auth(token_b)
    ).json()["id"]

    resp = client.post(
        f"/venues/{venue_a_id}/ingredients",
        json={
            "name": "Tomato", "unit": "kg", "ordering_unit": "crate",
            "preferred_supplier_id": supplier_b_id,
        },
        headers=_auth(token_a),
    )
    assert resp.status_code == 422


def test_create_and_list_menu_item(session):  # noqa: ARG001
    token, venue_id = _signup("c4owner@example.com", "C4 Co", "C4 Diner")
    resp = client.post(f"/venues/{venue_id}/menu-items", json={"name": "Cheeseburger"}, headers=_auth(token))
    assert resp.status_code == 201
    listing = client.get(f"/venues/{venue_id}/menu-items", headers=_auth(token))
    assert [m["name"] for m in listing.json()] == ["Cheeseburger"]


def test_create_and_list_equipment_item(session):  # noqa: ARG001
    token, venue_id = _signup("c5owner@example.com", "C5 Co", "C5 Diner")
    resp = client.post(
        f"/venues/{venue_id}/equipment-items",
        json={"name": "Walk-in Fridge", "location": "Back of house"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "active"


def test_line_staff_cannot_create_catalog_entries_but_can_read(session):  # noqa: ARG001
    owner_token, venue_id = _signup("c6owner@example.com", "C6 Co", "C6 Diner")
    client.post(
        f"/venues/{venue_id}/invite",
        json={"email": "c6line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("c6line@example.com")

    assert client.post(
        f"/venues/{venue_id}/suppliers", json={"name": "Hack"}, headers=_auth(line_token)
    ).status_code == 403
    assert client.get(f"/venues/{venue_id}/suppliers", headers=_auth(line_token)).status_code == 200


def test_catalog_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("c7ownerA@example.com", "C7A Co", "C7A Diner")
    token_b, venue_b_id = _signup("c7ownerB@example.com", "C7B Co", "C7B Diner")

    assert client.get(f"/venues/{venue_b_id}/suppliers", headers=_auth(token_a)).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/menu-items", json={"name": "Hack"}, headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/equipment-items", json={"name": "Hack"}, headers=_auth(token_a)
    ).status_code == 403
