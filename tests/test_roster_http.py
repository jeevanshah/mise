from datetime import date

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

def _user_id(token: str) -> str:
    return client.get("/auth/me", headers=_auth(token)).json()["id"]


def _station(token: str, venue_id: str, name: str = "Grill") -> str:
    return client.post(f"/venues/{venue_id}/stations", json={"name": name}, headers=_auth(token)).json()["id"]


def _staff(token: str, venue_id: str, name: str = "Alex", user_id: str | None = None) -> str:
    body = {"name": name}
    if user_id is not None:
        body["user_id"] = user_id
    return client.post(f"/venues/{venue_id}/staff", json=body, headers=_auth(token)).json()["id"]


def _create_shift(token, venue_id, station_id, staff_id, start_at, end_at):
    return client.post(
        f"/venues/{venue_id}/shifts",
        json={"station_id": station_id, "staff_id": staff_id, "start_at": start_at, "end_at": end_at},
        headers=_auth(token),
    )


def test_create_shift_and_list_by_week(session):  # noqa: ARG001
    token, venue_id = _signup("r1owner@example.com", "R1 Co", "R1 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)

    resp = _create_shift(
        token, venue_id, station_id, staff_id,
        "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00",
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "draft"
    assert resp.json()["response"]["status"] == "pending"

    listing = client.get(
        f"/venues/{venue_id}/shifts", params={"week_start": "2026-06-01"}, headers=_auth(token)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_list_shifts_requires_exactly_one_filter(session):  # noqa: ARG001
    token, venue_id = _signup("r2owner@example.com", "R2 Co", "R2 Diner")
    assert client.get(f"/venues/{venue_id}/shifts", headers=_auth(token)).status_code == 422
    assert client.get(
        f"/venues/{venue_id}/shifts",
        params={"week_start": "2026-06-01", "business_date": "2026-06-01"},
        headers=_auth(token),
    ).status_code == 422


def test_overlapping_shift_is_409(session):  # noqa: ARG001
    token, venue_id = _signup("r3owner@example.com", "R3 Co", "R3 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    _create_shift(token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00")

    conflict = _create_shift(
        token, venue_id, station_id, staff_id, "2026-06-01T16:00:00+10:00", "2026-06-01T20:00:00+10:00"
    )
    assert conflict.status_code == 409


def test_line_staff_cannot_create_shift_but_can_list(session):  # noqa: ARG001
    owner_token, venue_id = _signup("r4owner@example.com", "R4 Co", "R4 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "r4line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("r4line@example.com")
    station_id = _station(owner_token, venue_id)
    staff_id = _staff(owner_token, venue_id)

    resp = _create_shift(
        line_token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    )
    assert resp.status_code == 403

    listing = client.get(
        f"/venues/{venue_id}/shifts", params={"week_start": "2026-06-01"}, headers=_auth(line_token)
    )
    assert listing.status_code == 200


def test_publish_shift_returns_dev_staff_link_token(session):  # noqa: ARG001
    token, venue_id = _signup("r5owner@example.com", "R5 Co", "R5 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    shift_id = _create_shift(
        token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]

    resp = client.post(f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["shift"]["status"] == "published"
    assert resp.json()["dev_staff_link_token"] is not None

    # republishing is a no-op, no new token
    again = client.post(f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(token))
    assert again.json()["dev_staff_link_token"] is None


def test_publish_week_publishes_multiple_shifts(session):  # noqa: ARG001
    token, venue_id = _signup("r6owner@example.com", "R6 Co", "R6 Diner")
    station_id = _station(token, venue_id)
    staff_a = _staff(token, venue_id, name="Alex")
    staff_b = _staff(token, venue_id, name="Sam")
    _create_shift(token, venue_id, station_id, staff_a, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00")
    _create_shift(token, venue_id, station_id, staff_b, "2026-06-02T09:00:00+10:00", "2026-06-02T17:00:00+10:00")

    resp = client.post(
        f"/venues/{venue_id}/rosters/publish-week", json={"week_start": "2026-06-01"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 2
    assert all(r["shift"]["status"] == "published" for r in results)


def test_cancel_shift(session):  # noqa: ARG001
    token, venue_id = _signup("r7owner@example.com", "R7 Co", "R7 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    shift_id = _create_shift(
        token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]

    resp = client.post(f"/venues/{venue_id}/shifts/{shift_id}/cancel", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_copy_week(session):  # noqa: ARG001
    token, venue_id = _signup("r8owner@example.com", "R8 Co", "R8 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id)
    _create_shift(token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00")

    resp = client.post(
        f"/venues/{venue_id}/rosters/copy-week",
        json={"source_week_start": "2026-06-01", "target_week_start": "2026-06-08"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    copied = resp.json()
    assert len(copied) == 1
    assert copied[0]["status"] == "draft"

    conflict = client.post(
        f"/venues/{venue_id}/rosters/copy-week",
        json={"source_week_start": "2026-06-01", "target_week_start": "2026-06-08"},
        headers=_auth(token),
    )
    assert conflict.status_code == 409


def test_respond_to_shift_as_logged_in_staff(session):  # noqa: ARG001
    owner_token, venue_id = _signup("r9owner@example.com", "R9 Co", "R9 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "r9staff@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    staff_token = _login("r9staff@example.com")
    staff_user_id = _user_id(staff_token)
    station_id = _station(owner_token, venue_id)
    staff_id = _staff(owner_token, venue_id, name="Staffer", user_id=staff_user_id)

    shift_id = _create_shift(
        owner_token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]
    client.post(f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(owner_token))

    resp = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/respond", json={"response": "confirmed"},
        headers=_auth(staff_token),
    )
    assert resp.status_code == 200
    assert resp.json()["response"]["status"] == "confirmed"
    assert resp.json()["response"]["responded_via"] == "login"


def test_cannot_respond_to_someone_elses_shift(session):  # noqa: ARG001
    owner_token, venue_id = _signup("r10owner@example.com", "R10 Co", "R10 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "r10a@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "r10b@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    a_token = _login("r10a@example.com")
    b_token = _login("r10b@example.com")
    a_user_id = _user_id(a_token)
    station_id = _station(owner_token, venue_id)
    staff_a_id = _staff(owner_token, venue_id, name="A", user_id=a_user_id)

    shift_id = _create_shift(
        owner_token, venue_id, station_id, staff_a_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]

    resp = client.post(
        f"/venues/{venue_id}/shifts/{shift_id}/respond", json={"response": "confirmed"},
        headers=_auth(b_token),
    )
    assert resp.status_code == 403


def test_respond_via_signed_staff_link_no_login(session):  # noqa: ARG001
    token, venue_id = _signup("r11owner@example.com", "R11 Co", "R11 Diner")
    station_id = _station(token, venue_id)
    staff_id = _staff(token, venue_id, name="LineCook")  # no user_id — no login exists
    shift_id = _create_shift(
        token, venue_id, station_id, staff_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]
    publish = client.post(f"/venues/{venue_id}/shifts/{shift_id}/publish", headers=_auth(token))
    link_token = publish.json()["dev_staff_link_token"]
    assert link_token is not None

    view = client.get(f"/staff-links/{link_token}")
    assert view.status_code == 200
    assert view.json()["response_status"] == "pending"

    resp = client.post(f"/staff-links/{link_token}/respond", json={"response": "declined"})
    assert resp.status_code == 200
    assert resp.json()["response_status"] == "declined"


def test_invalid_staff_link_is_404(session):  # noqa: ARG001
    resp = client.get("/staff-links/not-a-real-token")
    assert resp.status_code == 404


def test_coverage_warnings_endpoint(session):  # noqa: ARG001
    token, venue_id = _signup("r12owner@example.com", "R12 Co", "R12 Diner")
    station_id = _station(token, venue_id)
    client.post(
        f"/venues/{venue_id}/stations/{station_id}/coverage-rules",
        json={"day_of_week": 0, "window_start": "17:00:00", "window_end": "22:00:00", "minimum_staff": 2},
        headers=_auth(token),
    )

    resp = client.get(
        f"/venues/{venue_id}/service-days/2026-06-01/coverage-warnings", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["scheduled_staff"] == 0


def test_roster_endpoints_are_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("r13ownerA@example.com", "R13A Co", "R13A Diner")
    token_b, venue_b_id = _signup("r13ownerB@example.com", "R13B Co", "R13B Diner")
    station_b_id = _station(token_b, venue_b_id)
    staff_b_id = _staff(token_b, venue_b_id)
    shift_b_id = _create_shift(
        token_b, venue_b_id, station_b_id, staff_b_id, "2026-06-01T09:00:00+10:00", "2026-06-01T17:00:00+10:00"
    ).json()["id"]

    assert client.get(
        f"/venues/{venue_b_id}/shifts", params={"week_start": "2026-06-01"}, headers=_auth(token_a)
    ).status_code == 403
    assert _create_shift(
        token_a, venue_b_id, station_b_id, staff_b_id, "2026-06-02T09:00:00+10:00", "2026-06-02T17:00:00+10:00"
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/shifts/{shift_b_id}/publish", headers=_auth(token_a)
    ).status_code == 403
    assert client.post(
        f"/venues/{venue_b_id}/shifts/{shift_b_id}/cancel", headers=_auth(token_a)
    ).status_code == 403
    assert client.get(
        f"/venues/{venue_b_id}/service-days/2026-06-01/coverage-warnings", headers=_auth(token_a)
    ).status_code == 403
