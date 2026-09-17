import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import supplier_order_service as sos
from app.services.supplier_order_service import ProviderSendResult

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


def _supplier(token, venue_id, contact_email="orders@fresh.co"):
    return client.post(
        f"/venues/{venue_id}/suppliers",
        json={"name": "Fresh Co", "contact_email": contact_email},
        headers=_auth(token),
    ).json()["id"]


def _ingredient(token, venue_id, name="Onions"):
    return client.post(
        f"/venues/{venue_id}/ingredients",
        json={"name": name, "unit": "kg", "ordering_unit": "carton"},
        headers=_auth(token),
    ).json()["id"]


@pytest.fixture(autouse=True)
def _reset_email_provider():
    original = sos.EMAIL_PROVIDER
    yield
    sos.EMAIL_PROVIDER = original


def test_add_line_creates_draft_and_second_add_merges(session):  # noqa: ARG001
    token, venue_id = _signup("po1owner@example.com", "PO1 Co", "PO1 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)

    first = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    )
    assert first.status_code == 200
    order = first.json()
    assert order["status"] == "draft"
    assert len(order["lines"]) == 1
    assert order["lines"][0]["unit"] == "carton"

    second = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "3", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    )
    merged = second.json()
    assert merged["id"] == order["id"]  # same draft, not a new one
    assert len(merged["lines"]) == 1
    assert merged["lines"][0]["quantity"] == "8.00"


def test_missing_identity_is_rejected(session):  # noqa: ARG001
    token, venue_id = _signup("po2owner@example.com", "PO2 Co", "PO2 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)

    resp = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={"supplier_id": supplier_id, "ingredient_id": ingredient_id, "quantity": "5"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_line_quantity_can_be_corrected_then_locked_after_send(session):  # noqa: ARG001
    token, venue_id = _signup("po3owner@example.com", "PO3 Co", "PO3 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()
    line_id = order["lines"][0]["id"]

    corrected = client.patch(
        f"/venues/{venue_id}/purchase-orders/{order['id']}/lines/{line_id}",
        json={"quantity": "12"}, headers=_auth(token),
    )
    assert corrected.status_code == 200
    assert corrected.json()["lines"][0]["quantity"] == "12.00"

    client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))

    locked = client.patch(
        f"/venues/{venue_id}/purchase-orders/{order['id']}/lines/{line_id}",
        json={"quantity": "1"}, headers=_auth(token),
    )
    assert locked.status_code == 409


def test_send_success_and_send_failed_paths(session):  # noqa: ARG001
    token, venue_id = _signup("po4owner@example.com", "PO4 Co", "PO4 Diner")
    supplier_id = _supplier(token, venue_id, contact_email="orders@fresh.co")
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()

    sent = client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))
    assert sent.status_code == 200
    body = sent.json()
    assert body["status"] == "sent"
    assert body["recipient_snapshot"] == "orders@fresh.co"
    assert body["provider_message_id"] is not None

    # Already-sent orders can't be sent again.
    again = client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))
    assert again.status_code == 409


def test_send_failed_shows_error_and_retry_succeeds(session):  # noqa: ARG001
    token, venue_id = _signup("po5owner@example.com", "PO5 Co", "PO5 Diner")
    supplier_id = _supplier(token, venue_id, contact_email=None)
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()

    failed = client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))
    body = failed.json()
    assert body["status"] == "send_failed"
    assert body["last_error"]
    first_key = body["idempotency_key"]

    def fake_success(*, supplier, purchase_order):  # noqa: ARG001
        return ProviderSendResult(message_id="retry-ok", recipient="fixed@fresh.co")

    sos.EMAIL_PROVIDER = fake_success
    retried = client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))
    retried_body = retried.json()
    assert retried_body["status"] == "sent"
    assert retried_body["idempotency_key"] == first_key  # reused, not regenerated


def test_sending_nonexistent_purchase_order_404s(session):  # noqa: ARG001
    token, venue_id = _signup("po6owner@example.com", "PO6 Co", "PO6 Diner")
    resp = client.post(
        f"/venues/{venue_id}/purchase-orders/00000000-0000-0000-0000-000000000000/send",
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_mark_delivery_full_and_partial(session):  # noqa: ARG001
    token, venue_id = _signup("po7owner@example.com", "PO7 Co", "PO7 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()
    client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))

    no_note = client.post(
        f"/venues/{venue_id}/purchase-orders/{order['id']}/delivery",
        json={"partial": True}, headers=_auth(token),
    )
    assert no_note.status_code == 422

    line_id = order["lines"][0]["id"]
    with_note = client.post(
        f"/venues/{venue_id}/purchase-orders/{order['id']}/delivery",
        json={"partial": True, "line_notes": {line_id: "2kg short"}},
        headers=_auth(token),
    )
    assert with_note.status_code == 200
    assert with_note.json()["delivery_status"] == "partially_received"
    assert with_note.json()["lines"][0]["delivery_note"] == "2kg short"


def test_log_delivery_issue(session):  # noqa: ARG001
    token, venue_id = _signup("po8owner@example.com", "PO8 Co", "PO8 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()
    client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))

    resp = client.post(
        f"/venues/{venue_id}/purchase-orders/{order['id']}/delivery-issues",
        json={"issue_type": "damaged", "evidence": "photo://stub.jpg"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert len(resp.json()["delivery_issues"]) == 1
    assert resp.json()["delivery_issues"][0]["issue_type"] == "damaged"


def test_list_purchase_orders_filters_by_status(session):  # noqa: ARG001
    token, venue_id = _signup("po9owner@example.com", "PO9 Co", "PO9 Diner")
    supplier_id = _supplier(token, venue_id)
    ingredient_id = _ingredient(token, venue_id)
    order = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "5", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token),
    ).json()
    client.post(f"/venues/{venue_id}/purchase-orders/{order['id']}/send", headers=_auth(token))
    client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "2", "required_delivery_date": "2026-06-17",
        },
        headers=_auth(token),
    )

    all_orders = client.get(f"/venues/{venue_id}/purchase-orders", headers=_auth(token)).json()
    assert len(all_orders) == 2

    drafts = client.get(f"/venues/{venue_id}/purchase-orders?status=draft", headers=_auth(token)).json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "draft"


def test_purchase_order_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("po10ownerA@example.com", "PO10A Co", "PO10A Diner")
    token_b, venue_b_id = _signup("po10ownerB@example.com", "PO10B Co", "PO10B Diner")
    supplier_id = _supplier(token_b, venue_b_id)
    ingredient_id = _ingredient(token_b, venue_b_id)

    assert client.get(f"/venues/{venue_b_id}/purchase-orders", headers=_auth(token_a)).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "1", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(token_a),
    ).status_code == 403


def test_only_management_roles_can_create_lines(session):  # noqa: ARG001
    owner_token, venue_id = _signup("po11owner@example.com", "PO11 Co", "PO11 Diner")
    supplier_id = _supplier(owner_token, venue_id)
    ingredient_id = _ingredient(owner_token, venue_id)

    client.post(
        f"/venues/{venue_id}/invite", json={"email": "po11line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("po11line@example.com")

    resp = client.post(
        f"/venues/{venue_id}/purchase-orders/lines",
        json={
            "supplier_id": supplier_id, "ingredient_id": ingredient_id,
            "quantity": "1", "required_delivery_date": "2026-06-10",
        },
        headers=_auth(line_token),
    )
    assert resp.status_code == 403
