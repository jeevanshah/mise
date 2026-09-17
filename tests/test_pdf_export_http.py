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


def _start_day(token, venue_id, business_date="2026-06-01"):
    resp = client.post(
        f"/venues/{venue_id}/service-days/start", json={"business_date": business_date}, headers=_auth(token)
    )
    assert resp.status_code == 200


def _station(token, venue_id, name="Grill"):
    return client.post(f"/venues/{venue_id}/stations", json={"name": name}, headers=_auth(token)).json()["id"]


def _staff(token, venue_id, name="Alex"):
    return client.post(f"/venues/{venue_id}/staff", json={"name": name}, headers=_auth(token)).json()["id"]


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


def _create_shift(token, venue_id, station_id, staff_id, start_at, end_at):
    return client.post(
        f"/venues/{venue_id}/shifts",
        json={"station_id": station_id, "staff_id": staff_id, "start_at": start_at, "end_at": end_at},
        headers=_auth(token),
    )


def test_handover_pdf_returns_a_pdf_after_close(session):  # noqa: ARG001
    token, venue_id = _signup("pdf1owner@example.com", "PDF1 Co", "PDF1 Diner")
    _start_day(token, venue_id)
    station_id = _station(token, venue_id)
    template_id = _template_with_item(token, venue_id, station_id)
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id}, headers=_auth(token),
    )
    client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/close", json={"note": "quiet night"}, headers=_auth(token)
    )

    resp = client.get(f"/venues/{venue_id}/service-days/2026-06-01/handover/pdf", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


def test_handover_pdf_404s_before_the_day_is_closed(session):  # noqa: ARG001
    token, venue_id = _signup("pdf2owner@example.com", "PDF2 Co", "PDF2 Diner")
    _start_day(token, venue_id)

    resp = client.get(f"/venues/{venue_id}/service-days/2026-06-01/handover/pdf", headers=_auth(token))
    assert resp.status_code == 404


def test_handover_pdf_is_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("pdf3ownerA@example.com", "PDF3A Co", "PDF3A Diner")
    _token_b, venue_b_id = _signup("pdf3ownerB@example.com", "PDF3B Co", "PDF3B Diner")
    _start_day(_token_b, venue_b_id)

    cross_tenant = client.get(
        f"/venues/{venue_b_id}/service-days/2026-06-01/handover/pdf", headers=_auth(token_a)
    )
    assert cross_tenant.status_code == 403


def test_roster_pdf_returns_a_pdf(session):  # noqa: ARG001
    token, venue_id = _signup("pdf4owner@example.com", "PDF4 Co", "PDF4 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    _create_shift(
        token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    )

    resp = client.get(
        f"/venues/{venue_id}/rosters/pdf", params={"week_start": "2026-06-01"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


def test_roster_pdf_with_no_shifts_still_returns_a_pdf(session):  # noqa: ARG001
    token, venue_id = _signup("pdf5owner@example.com", "PDF5 Co", "PDF5 Diner")

    resp = client.get(
        f"/venues/{venue_id}/rosters/pdf", params={"week_start": "2026-06-01"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


def test_roster_pdf_is_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("pdf6ownerA@example.com", "PDF6A Co", "PDF6A Diner")
    _token_b, venue_b_id = _signup("pdf6ownerB@example.com", "PDF6B Co", "PDF6B Diner")

    cross_tenant = client.get(
        f"/venues/{venue_b_id}/rosters/pdf", params={"week_start": "2026-06-01"}, headers=_auth(token_a)
    )
    assert cross_tenant.status_code == 403


def test_pdf_endpoints_require_some_membership(session):  # noqa: ARG001
    owner_token, venue_id = _signup("pdf7owner@example.com", "PDF7 Co", "PDF7 Diner")
    outsider_token = _login("pdf7outsider@example.com")

    handover_resp = client.get(
        f"/venues/{venue_id}/service-days/2026-06-01/handover/pdf", headers=_auth(outsider_token)
    )
    roster_resp = client.get(
        f"/venues/{venue_id}/rosters/pdf", params={"week_start": "2026-06-01"}, headers=_auth(outsider_token)
    )

    assert handover_resp.status_code == 403
    assert roster_resp.status_code == 403
