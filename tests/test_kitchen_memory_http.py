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


def _ingredient(token, venue_id, name="Onions"):
    return client.post(
        f"/venues/{venue_id}/ingredients", json={"name": name, "unit": "kg", "ordering_unit": "sack"},
        headers=_auth(token),
    ).json()["id"]


def _menu_item(token, venue_id, name="Cheeseburger"):
    return client.post(f"/venues/{venue_id}/menu-items", json={"name": name}, headers=_auth(token)).json()["id"]


def _equipment_item(token, venue_id, name="Stand Mixer"):
    return client.post(f"/venues/{venue_id}/equipment-items", json={"name": name}, headers=_auth(token)).json()["id"]


def _recipe(token, venue_id, name="Bun"):
    return client.post(f"/venues/{venue_id}/recipes", json={"name": name}, headers=_auth(token)).json()["id"]


def test_create_recipe_and_versions(session):  # noqa: ARG001
    token, venue_id = _signup("km1owner@example.com", "KM1 Co", "KM1 Diner")
    ingredient_id = _ingredient(token, venue_id)
    recipe_id = _recipe(token, venue_id, "House Vinaigrette")

    v1 = client.post(
        f"/venues/{venue_id}/recipes/{recipe_id}/versions",
        json={
            "yield_qty": "1", "yield_unit": "litre", "prep_notes": "Whisk well",
            "ingredients": [{"ingredient_id": ingredient_id, "quantity": "2", "unit": "kg"}],
        },
        headers=_auth(token),
    )
    assert v1.status_code == 201
    assert v1.json()["version_no"] == 1
    assert v1.json()["ingredients"][0]["ingredient_name"] == "Onions"

    v2 = client.post(
        f"/venues/{venue_id}/recipes/{recipe_id}/versions",
        json={"prep_notes": "Whisk even harder", "ingredients": []},
        headers=_auth(token),
    )
    assert v2.json()["version_no"] == 2

    detail = client.get(f"/venues/{venue_id}/recipes/{recipe_id}", headers=_auth(token))
    assert detail.json()["current_version"]["version_no"] == 2
    assert detail.json()["version_count"] == 2

    history = client.get(f"/venues/{venue_id}/recipes/{recipe_id}/versions", headers=_auth(token))
    assert [v["version_no"] for v in history.json()] == [1, 2]
    assert history.json()[0]["prep_notes"] == "Whisk well"  # old version still viewable


def test_menu_item_detail_shows_linked_recipes(session):  # noqa: ARG001
    token, venue_id = _signup("km2owner@example.com", "KM2 Co", "KM2 Diner")
    bun_id = _recipe(token, venue_id, "Bun")
    patty_id = _recipe(token, venue_id, "Patty")
    menu_item_id = _menu_item(token, venue_id, "Cheeseburger")

    client.post(f"/venues/{venue_id}/menu-items/{menu_item_id}/recipes", json={"recipe_id": bun_id}, headers=_auth(token))
    client.post(f"/venues/{venue_id}/menu-items/{menu_item_id}/recipes", json={"recipe_id": patty_id}, headers=_auth(token))

    detail = client.get(f"/venues/{venue_id}/menu-items/{menu_item_id}", headers=_auth(token))
    assert detail.status_code == 200
    names = {r["name"] for r in detail.json()["recipes"]}
    assert names == {"Bun", "Patty"}


def test_linking_the_same_recipe_twice_is_a_409(session):  # noqa: ARG001
    token, venue_id = _signup("km3owner@example.com", "KM3 Co", "KM3 Diner")
    recipe_id = _recipe(token, venue_id)
    menu_item_id = _menu_item(token, venue_id)
    client.post(f"/venues/{venue_id}/menu-items/{menu_item_id}/recipes", json={"recipe_id": recipe_id}, headers=_auth(token))

    again = client.post(
        f"/venues/{venue_id}/menu-items/{menu_item_id}/recipes", json={"recipe_id": recipe_id}, headers=_auth(token)
    )
    assert again.status_code == 409


def test_equipment_issue_history_endpoint(session):  # noqa: ARG001
    token, venue_id = _signup("km4owner@example.com", "KM4 Co", "KM4 Diner")
    equipment_id = _equipment_item(token, venue_id)
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "the stand mixer is broken"}, headers=_auth(token)
    ).json()
    client.post(f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(token))

    resp = client.get(f"/venues/{venue_id}/equipment-items/{equipment_id}/issues", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["equipment_item"]["name"] == "Stand Mixer"
    assert len(body["issues"]) == 1


def test_search_endpoint_finds_recipe_and_is_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("km5ownerA@example.com", "KM5A Co", "KM5A Diner")
    token_b, venue_b_id = _signup("km5ownerB@example.com", "KM5B Co", "KM5B Diner")
    _recipe(token_a, venue_a_id, "House Vinaigrette")

    hit = client.get(f"/venues/{venue_a_id}/kitchen-memory/search?q=vinaigrette", headers=_auth(token_a))
    assert hit.status_code == 200
    assert len(hit.json()) == 1
    assert hit.json()[0]["result_type"] == "recipe"

    miss_other_venue = client.get(
        f"/venues/{venue_b_id}/kitchen-memory/search?q=vinaigrette", headers=_auth(token_b)
    )
    assert miss_other_venue.json() == []

    cross_tenant = client.get(f"/venues/{venue_b_id}/kitchen-memory/search?q=vinaigrette", headers=_auth(token_a))
    assert cross_tenant.status_code == 403


def test_only_management_roles_can_create_recipes(session):  # noqa: ARG001
    owner_token, venue_id = _signup("km6owner@example.com", "KM6 Co", "KM6 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "km6line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("km6line@example.com")

    resp = client.post(f"/venues/{venue_id}/recipes", json={"name": "Bun"}, headers=_auth(line_token))
    assert resp.status_code == 403
