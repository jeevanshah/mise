from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.equipment import EquipmentIssue
from app.services import email_service

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


@pytest.fixture(autouse=True)
def _reset_email_sender():
    original = email_service.EMAIL_SENDER
    yield
    email_service.EMAIL_SENDER = original


def _stale_equipment_issue(token, venue_id, session):
    client.post(f"/venues/{venue_id}/equipment-items", json={"name": "Stand Mixer"}, headers=_auth(token))
    capture = client.post(
        f"/venues/{venue_id}/captures", json={"raw_text": "the stand mixer is broken"}, headers=_auth(token)
    ).json()
    client.post(f"/venues/{venue_id}/captures/{capture['id']}/confirm", json={}, headers=_auth(token))

    issue = session.query(EquipmentIssue).order_by(EquipmentIssue.opened_at.desc()).first()
    issue.opened_at = datetime.now(timezone.utc) - timedelta(hours=25)
    session.add(issue)
    session.commit()
    return issue


def test_run_checks_notifies_and_returns_sent_notifications(session):
    sent = []
    email_service.EMAIL_SENDER = lambda message: (
        sent.append(message) or email_service.SentEmail(message_id="http-test-id", to=message.to)
    )
    token, venue_id = _signup("n1owner@example.com", "N1 Co", "N1 Diner")
    _stale_equipment_issue(token, venue_id, session)

    resp = client.post(f"/venues/{venue_id}/notifications/run-checks", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["action"] == "notification.equipment_issue_stale"
    assert body[0]["recipients"] == ["n1owner@example.com"]
    assert [m.to for m in sent] == ["n1owner@example.com"]


def test_run_checks_does_not_re_notify_the_same_trigger(session):
    token, venue_id = _signup("n2owner@example.com", "N2 Co", "N2 Diner")
    _stale_equipment_issue(token, venue_id, session)

    first = client.post(f"/venues/{venue_id}/notifications/run-checks", headers=_auth(token))
    second = client.post(f"/venues/{venue_id}/notifications/run-checks", headers=_auth(token))

    assert len(first.json()) == 1
    assert second.json() == []


def test_only_management_roles_can_trigger_checks(session):  # noqa: ARG001
    owner_token, venue_id = _signup("n3owner@example.com", "N3 Co", "N3 Diner")
    client.post(
        f"/venues/{venue_id}/invite", json={"email": "n3line@example.com", "role": "line_staff"},
        headers=_auth(owner_token),
    )
    line_token = _login("n3line@example.com")

    resp = client.post(f"/venues/{venue_id}/notifications/run-checks", headers=_auth(line_token))
    assert resp.status_code == 403


def test_run_checks_is_venue_scoped(session):  # noqa: ARG001
    token_a, venue_a_id = _signup("n4ownerA@example.com", "N4A Co", "N4A Diner")
    _token_b, venue_b_id = _signup("n4ownerB@example.com", "N4B Co", "N4B Diner")

    cross_tenant = client.post(f"/venues/{venue_b_id}/notifications/run-checks", headers=_auth(token_a))
    assert cross_tenant.status_code == 403
