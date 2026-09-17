# Mise API

Epic 1 (Foundation, Onboarding & Audit) of the locked Rev 4 spec — **complete**, all 9 steps. FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL.

## What's built

- **Step 1 — Repository, CI, environments:** this scaffold, `docker-compose.yml` for local Postgres, `.github/workflows/ci.yml` (spins up Postgres, verifies migrations are reversible, runs the test suite).
- **Step 2 — PostgreSQL migrations:** `migrations/versions/0001_epic1_foundation_schema.py` — every Epic 1 entity (Organisation, Venue, User, Membership, Staff/StaffSkill, Station/StationCoverageRule, ServiceDay, Supplier, Ingredient, MenuItem, Recipe/RecipeVersion/RecipeIngredient/MenuItemRecipe, EquipmentItem, AuditEvent). Generated with `alembic revision --autogenerate` against a real Postgres instance, then hand-fixed for a real bug autogenerate doesn't catch: **Postgres ENUM types aren't dropped automatically on `downgrade()`** — without the fix, `upgrade → downgrade → upgrade` fails with "type already exists". Verified with a full down/up cycle.
- **Step 3 — Atomic AuditEvent helper:** `app/services/audit_service.py`. `audited_transaction(...)` stages a mutation and its AuditEvent(s) on one session and commits once; any exception rolls back both. Tested in `tests/test_audit_atomicity.py`, including the failure-mid-transaction case.
- **Step 4 — Authentication and Membership permissions:** `migrations/versions/0002_epic1_step4_magic_links.py` adds `magic_links`. `app/services/auth_service.py` issues/verifies single-use, hashed, expiring magic-link tokens (`POST /auth/request-link`, `POST /auth/verify`) and signs/decodes JWT access tokens; `app/api/deps.py` provides `get_current_user` and `require_membership(*roles)`, which re-queries `Membership` on every request. `GET /auth/me` proves the chain end-to-end. No email provider exists yet (Epic 10), so `request-link` returns the raw token directly in the response outside `ENVIRONMENT=production`.
- **Step 5 — Org/Venue onboarding:** `app/services/onboarding_service.py`. `POST /organisations` is the "sign up" step — any authenticated User creates an Organisation + Venue and becomes its `owner` Membership, atomically. `PATCH /venues/{id}` (owner-only) edits `timezone`/`business_day_boundary`. `POST /venues/{id}/invite` (owner-only) finds-or-creates the invitee by email and grants a Membership (409 if they're already a member, not a silent role change).
- **Step 6 — Staff/Stations/Coverage:** `app/services/staffing_service.py`. Stations, Staff (creatable with zero Users attached, per the AC), StaffSkill (409 on a duplicate staff×station row), StationCoverageRule (day-of-week + time window, `window_start < window_end` enforced, 409 on an exact duplicate rule). Management actions (create/modify) need `MANAGEMENT_ROLES` (owner/ops_manager/head_chef); reads need any Membership.
- **Step 7 — Suppliers/Ingredients/Menu/Equipment:** `app/services/catalog_service.py`. Create+list for all four — Recipe/RecipeVersion/RecipeIngredient stay schema-only per the locked entity list ("skeleton"; full CRUD is Epic 9). `Ingredient.preferred_supplier_id` is validated against the SAME venue — accepting a cross-venue supplier id would be a tenancy leak via a foreign key, not just a data-integrity nicety.
- **Step 8 — ServiceDay lifecycle:** `app/services/service_day_service.py`. `resolve_business_date(venue, at)` implements the "business_date ≠ calendar date" rule using `zoneinfo` (stdlib, no extra timezone dependency beyond `tzdata` for portability) — tested against the exact locked-spec scenario (a dinner service ending 1am is still the prior business_date) plus a same-instant comparison across two different venue timezones and a custom boundary. `get_or_create_service_day` is the lazy-creation half; `open_service_day` is the idempotent, audited `planned → open` transition. `GET /venues/{id}/service-days/current` and `POST /venues/{id}/service-days/start` expose both end to end (no Epic 2 entity yet triggers this automatically, so these routes are how it's proven live rather than left as an untested function).
- **Step 9 — Tenancy:** the data-layer half lives in `tests/test_tenancy.py`; the HTTP-level half is proven against real endpoints in every `test_*_http.py` file (not just a single throwaway route) — a Membership at Venue A gets 403 at Venue B for every resource type (stations, staff, suppliers, service-days, ...), and a nonexistent venue 403s identically to one owned by someone else so the response never leaks which venue IDs exist.

**Epic 1 is done.** Epic 2 (Kitchen Roster) is next per the locked build order, but is gated on confirming the service-period question with the customer (lunch/dinner/events as separate `ServicePeriod` tracking vs. one `ServiceDay` per day) — see the epics doc. Don't start Epic 2 assuming the documented default without checking that's still current.

## Local setup

```bash
cp .env.example .env
docker compose up -d db          # or point DATABASE_URL at your own Postgres
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload    # GET /health
```

## Tests

Tests run against a **separate** database (`mise_test` by default — see `tests/conftest.py`) using `Base.metadata.create_all`/`drop_all` directly, independent of the Alembic migration path, so a model/migration drift shows up as a CI failure in the "reversible migrations" step, not a silently-passing test suite.

```bash
createdb mise_test   # once, locally — CI does this via the postgres service container
pytest tests/ -v     # 87 tests
```

## Design notes worth knowing before extending this

- **UUID primary keys**, generated app-side (`uuid.uuid4()`), not DB-side — no `pgcrypto` extension dependency.
- **`business_date` is not the calendar date.** See `app/services/service_day_service.py::resolve_business_date` — don't compute it ad hoc anywhere else.
- **`Staff.user_id` is nullable on purpose.** Line staff don't need a login.
- **`MenuItem` and `Recipe` are different tables**, linked by `MenuItemRecipe` — a burger can reference a patty recipe and a sauce recipe.
- **`AuditEvent` is append-only.** Always write it through `audited_transaction`, never with a separate `session.add()` + its own commit.
- **Login is magic-link only — no passwords anywhere.** `POST /auth/request-link` finds-or-creates the `User` by email; that's also how a brand-new owner "signs up" — `POST /organisations` is the first real action they take once logged in.
- **Multi-row creates (Organisation+Venue+Membership, or a lazily-created ServiceDay immediately opened) commit as one transaction**, not several. The pattern: flush the entities that don't exist yet to get their ids, THEN open `audited_transaction` for the rest — its one `commit()` covers everything pending on the session, so a failure anywhere rolls back all of it. See `onboarding_service.create_organisation_with_venue`'s docstring.
- **Role checks always hit the DB, never the token.** `require_membership` looks up `Membership` fresh on every request — a revoked Membership takes effect on the very next request, not whenever the JWT expires.
- **A 403 from `require_membership` never distinguishes "wrong role" from "venue doesn't exist" from "belongs to someone else"** in a way that leaks across tenants.
- **`MANAGEMENT_ROLES`** (`app/api/deps.py`: owner, ops_manager, head_chef) gates every "configure the venue" action (stations, staff, coverage rules, suppliers, ingredients, menu items, equipment). sous_chef/line_staff can read but not configure. Reuse this constant rather than redefining the role set per router.
- **A duplicate create is a 409, never a silent update.** StaffSkill, StationCoverageRule, and inviting an existing Membership all follow this — see each service module's `Duplicate*` exception classes.
