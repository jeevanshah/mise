"""
Epic 11 — Role x module permission test matrix (locked AC).

This epic doesn't build the permission system (that's app/api/deps.py,
Epic 1 step 4) — it verifies it, the same "finds gaps, doesn't build the
logger" framing the locked AC uses for audit coverage. Every module that
gates a write behind a role gets its own check here, run against all five
MembershipRole values, so a mistaken role set on any one route (the wrong
tuple copy-pasted, a role left out) shows up as a failing assertion instead
of an unnoticed gap.

Three tiers are covered, matching the three role-sets actually used
anywhere in the app (app/api/deps.py):
  - owner-only (onboarding's venue-settings edit)
  - MANAGEMENT_ROLES = owner, ops_manager, head_chef (every module below)
  - PREP_EXECUTION_ROLES = head_chef, sous_chef (prep task status only —
    deliberately narrower than MANAGEMENT_ROLES and NOT a superset of it,
    the one tier worth checking on its own since owner/ops_manager are
    excluded from it)
Every module's own read endpoint is also checked to confirm "any
Membership can read" actually holds for all five roles, not just the ones
that can write.

Signed-link scope limits (a link only ever reaching its own Shift, revoked
on cancel, unable to reach another Staff's records even with a guessed
token) are exercised per-epic already (test_roster_service.py,
test_attendance_service.py) — this file is the write/read role matrix,
not a re-run of those.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ALL_ROLES = ["owner", "ops_manager", "head_chef", "sous_chef", "line_staff"]
MANAGEMENT_ROLES = {"owner", "ops_manager", "head_chef"}
PREP_EXECUTION_ROLES = {"head_chef", "sous_chef"}
OWNER_ONLY = {"owner"}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str) -> str:
    dev_token = client.post("/auth/request-link", json={"email": email}).json()["dev_token"]
    return client.post("/auth/verify", json={"token": dev_token}).json()["access_token"]


def _setup_venue_with_all_roles(prefix: str) -> tuple[str, dict[str, str]]:
    """Signs up an owner, invites one Membership per remaining role, and
    returns (venue_id, {role: token}) — every module check below builds on
    this same five-role venue."""
    owner_email = f"{prefix}owner@example.com"
    owner_token = _login(owner_email)
    venue_id = client.post(
        "/organisations", json={"organisation_name": f"{prefix} Co", "venue_name": f"{prefix} Diner"},
        headers=_auth(owner_token),
    ).json()["venue"]["id"]

    tokens = {"owner": owner_token}
    for role in ALL_ROLES:
        if role == "owner":
            continue
        email = f"{prefix}{role}@example.com"
        client.post(
            f"/venues/{venue_id}/invite", json={"email": email, "role": role}, headers=_auth(owner_token)
        )
        tokens[role] = _login(email)
    return venue_id, tokens


def _assert_matches_tier(resp, role: str, allowed: set[str]) -> None:
    if role in allowed:
        assert resp.status_code < 400, f"{role} should be allowed, got {resp.status_code}: {resp.text}"
    else:
        assert resp.status_code == 403, f"{role} should be forbidden, got {resp.status_code}: {resp.text}"


def test_onboarding_venue_settings_is_owner_only(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm1")
    for role in ALL_ROLES:
        resp = client.patch(
            f"/venues/{venue_id}", json={"timezone": "Australia/Perth"}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, OWNER_ONLY)


def test_staffing_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm2")
    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/staff", json={"name": f"Staff-{role}"}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)
    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/staff", headers=_auth(tokens[role]))
        assert resp.status_code == 200, f"{role} should be able to read staff, got {resp.status_code}"


def test_catalog_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm3")
    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/suppliers", json={"name": f"Supplier-{role}"}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)
    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/suppliers", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_service_days_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm4")
    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/service-days/start", json={}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)
    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/service-days/current", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_roster_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm5")
    station_id = client.post(
        f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(tokens["owner"])
    ).json()["id"]

    for role in ALL_ROLES:
        staff_id = client.post(
            f"/venues/{venue_id}/staff", json={"name": f"Staff-{role}"}, headers=_auth(tokens["owner"])
        ).json()["id"]
        resp = client.post(
            f"/venues/{venue_id}/shifts",
            json={
                "station_id": station_id, "staff_id": staff_id,
                "start_at": "2026-06-01T09:00:00+10:00", "end_at": "2026-06-01T17:00:00+10:00",
            },
            headers=_auth(tokens[role]),
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    for role in ALL_ROLES:
        resp = client.get(
            f"/venues/{venue_id}/service-days/2026-06-01/coverage-warnings", headers=_auth(tokens[role])
        )
        assert resp.status_code == 200


def test_attendance_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm6")
    station_id = client.post(
        f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(tokens["owner"])
    ).json()["id"]
    staff_id = client.post(
        f"/venues/{venue_id}/staff", json={"name": "Alex"}, headers=_auth(tokens["owner"])
    ).json()["id"]
    shift_id = client.post(
        f"/venues/{venue_id}/shifts",
        json={
            "station_id": station_id, "staff_id": staff_id,
            "start_at": "2026-06-01T09:00:00+10:00", "end_at": "2026-06-01T17:00:00+10:00",
        },
        headers=_auth(tokens["owner"]),
    ).json()["id"]

    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/shifts/{shift_id}/attendance-events",
            json={"status": "present"}, headers=_auth(tokens[role]),
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/shifts/{shift_id}/attendance", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_prep_module_templates_are_management_only_and_status_updates_are_narrower(session):  # noqa: ARG001
    """The interesting tier here is PREP_EXECUTION_ROLES on the status
    update — deliberately NOT a superset of MANAGEMENT_ROLES: owner and
    ops_manager configure the venue but don't execute the pass, so they're
    excluded from this one action even though they can do almost
    everything else."""
    venue_id, tokens = _setup_venue_with_all_roles("pm7")
    station_id = client.post(
        f"/venues/{venue_id}/stations", json={"name": "Grill"}, headers=_auth(tokens["owner"])
    ).json()["id"]

    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/prep-templates", json={"name": f"Template-{role}"}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    template_id = client.post(
        f"/venues/{venue_id}/prep-templates", json={"name": "Dinner prep"}, headers=_auth(tokens["owner"])
    ).json()["id"]
    client.post(
        f"/venues/{venue_id}/prep-templates/{template_id}/items",
        json={"station_id": station_id, "item": "Mise en place", "quantity": "1", "unit": "batch"},
        headers=_auth(tokens["owner"]),
    )
    tasks = client.post(
        f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks/apply-template",
        json={"template_id": template_id},
        headers=_auth(tokens["owner"]),
    ).json()
    task_id = tasks[0]["id"]

    for role in ALL_ROLES:
        resp = client.patch(
            f"/venues/{venue_id}/prep-tasks/{task_id}/status",
            json={"status": "in_progress"}, headers=_auth(tokens[role]),
        )
        _assert_matches_tier(resp, role, PREP_EXECUTION_ROLES)

    for role in ALL_ROLES:
        resp = client.get(
            f"/venues/{venue_id}/service-days/2026-06-01/prep-tasks", headers=_auth(tokens[role])
        )
        assert resp.status_code == 200


def test_purchase_order_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm8")
    supplier_id = client.post(
        f"/venues/{venue_id}/suppliers", json={"name": "Fresh Co"}, headers=_auth(tokens["owner"])
    ).json()["id"]
    ingredient_id = client.post(
        f"/venues/{venue_id}/ingredients",
        json={"name": "Onions", "unit": "kg", "ordering_unit": "sack"}, headers=_auth(tokens["owner"]),
    ).json()["id"]

    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/purchase-orders/lines",
            json={
                "supplier_id": supplier_id, "ingredient_id": ingredient_id,
                "quantity": "1", "required_delivery_date": "2026-06-10",
            },
            headers=_auth(tokens[role]),
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/purchase-orders", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_capture_module_create_is_any_membership_confirm_is_management(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm9")
    # A confident classifier match, so confirm() doesn't 422 for reasons
    # unrelated to the role check — see MatchedEntityType/EquipmentItem.
    client.post(
        f"/venues/{venue_id}/equipment-items", json={"name": "Stand Mixer"}, headers=_auth(tokens["owner"])
    )

    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/captures",
            json={"raw_text": "the stand mixer is broken"}, headers=_auth(tokens[role]),
        )
        assert resp.status_code == 201, f"any Membership should be able to create a capture, {role} got {resp.status_code}"
        capture_id = resp.json()["id"]

        confirm_resp = client.post(
            f"/venues/{venue_id}/captures/{capture_id}/confirm", json={}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(confirm_resp, role, MANAGEMENT_ROLES)

    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/captures", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_handover_module(session):  # noqa: ARG001
    """Close can only succeed once per ServiceDay (locked AC: a single
    open->close event) — a distinct business_date per role, each freshly
    opened by the owner, so one role's successful close never turns into a
    409-already-closed for the next role tested."""
    venue_id, tokens = _setup_venue_with_all_roles("pm10")

    for i, role in enumerate(ALL_ROLES):
        business_date = f"2026-06-{i + 1:02d}"
        client.post(
            f"/venues/{venue_id}/service-days/start", json={"business_date": business_date},
            headers=_auth(tokens["owner"]),
        )
        resp = client.post(
            f"/venues/{venue_id}/service-days/{business_date}/close", json={}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    closed_business_date = "2026-06-01"  # ALL_ROLES[0] == "owner", closed above
    for role in ALL_ROLES:
        resp = client.get(
            f"/venues/{venue_id}/service-days/{closed_business_date}/handover", headers=_auth(tokens[role])
        )
        assert resp.status_code == 200


def test_chef_brief_module_is_any_membership_read_only(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm11")
    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/chef-brief", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_kitchen_memory_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm12")
    for role in ALL_ROLES:
        resp = client.post(
            f"/venues/{venue_id}/recipes", json={"name": f"Recipe-{role}"}, headers=_auth(tokens[role])
        )
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)

    for role in ALL_ROLES:
        resp = client.get(f"/venues/{venue_id}/recipes", headers=_auth(tokens[role]))
        assert resp.status_code == 200


def test_notification_module(session):  # noqa: ARG001
    venue_id, tokens = _setup_venue_with_all_roles("pm13")
    for role in ALL_ROLES:
        resp = client.post(f"/venues/{venue_id}/notifications/run-checks", json={}, headers=_auth(tokens[role]))
        _assert_matches_tier(resp, role, MANAGEMENT_ROLES)
