# Mise API

Epic 1 (Foundation, Onboarding & Audit) of the locked Rev 4 spec. FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL.

## What's built (Epic 1, steps 1–5)

- **Step 1 — Repository, CI, environments:** this scaffold, `docker-compose.yml` for local Postgres, `.github/workflows/ci.yml` (spins up Postgres, verifies migrations are reversible, runs the test suite).
- **Step 2 — PostgreSQL migrations:** `migrations/versions/0001_epic1_foundation_schema.py` — every Epic 1 entity (Organisation, Venue, User, Membership, Staff/StaffSkill, Station/StationCoverageRule, ServiceDay, Supplier, Ingredient, MenuItem, Recipe/RecipeVersion/RecipeIngredient/MenuItemRecipe, EquipmentItem, AuditEvent). Generated with `alembic revision --autogenerate` against a real Postgres instance, then hand-fixed for a real bug autogenerate doesn't catch: **Postgres ENUM types aren't dropped automatically on `downgrade()`** — without the fix, `upgrade → downgrade → upgrade` fails with "type already exists". Verified with a full down/up cycle.
- **Step 3 — Atomic AuditEvent helper:** `app/services/audit_service.py`. `audited_transaction(...)` stages a mutation and its AuditEvent(s) on one session and commits once; any exception rolls back both. Tested in `tests/test_audit_atomicity.py`, including the failure-mid-transaction case (proves no orphan AuditEvent survives a rollback).
- **Step 4 — Authentication and Membership permissions:** `migrations/versions/0002_epic1_step4_magic_links.py` adds `magic_links`. `app/services/auth_service.py` issues/verifies single-use, hashed, expiring magic-link tokens (`POST /auth/request-link`, `POST /auth/verify`) and signs/decodes JWT access tokens; `app/api/deps.py` provides `get_current_user` and `require_membership(*roles)`, which re-queries `Membership` on every request (no role baked into the token, so a revoked Membership takes effect immediately, not at token expiry). `GET /auth/me` proves the chain end-to-end. No email provider exists yet (Epic 10), so `request-link` returns the raw token directly in the response outside `ENVIRONMENT=production`. `tests/test_tenancy.py` now also has the HTTP-level half: a real request, with a real signed token, against a real `require_membership`-protected route, proving Venue A's Membership is refused (403) at Venue B — and that a nonexistent venue 403s identically to one owned by someone else, so the response never leaks which venue IDs exist.

- **Step 5 — Org/Venue onboarding endpoints:** `app/services/onboarding_service.py` + `app/api/routes/onboarding.py`. `POST /organisations` is the "sign up" step — any authenticated User (i.e. anyone who's completed magic-link login) creates an Organisation + Venue and becomes its `owner` Membership, atomically (Organisation/Venue are flushed to get their ids, then a single `audited_transaction` covers the Membership insert plus three AuditEvents and the one commit — fail anywhere and none of it persists, org/venue included). `PATCH /venues/{id}` (owner-only) edits `timezone`/`business_day_boundary` after creation, per the AC that they're "editable". `POST /venues/{id}/invite` (owner-only) finds-or-creates the invitee by email and grants a Membership — reusing the same find-or-create helper as magic-link login (`app/services/user_service.py`) so an invited person can immediately log in with their own email. Inviting someone already a member is a 409, not a silent role change. `GET /venues/{id}` needs any Membership. All three mutations write AuditEvents; verified end-to-end against a live server (signup → invite → invited user logs in and sees the right role → non-owner blocked from inviting/editing) and cross-venue tenancy re-verified through these real endpoints in `tests/test_onboarding_http.py`, not just the throwaway route in `test_tenancy.py`.

**Not built yet** (per the locked order — next up): step 6 Staff/Stations/Coverage endpoints, step 7 Suppliers/Ingredients/Menu/Equipment endpoints, step 8 ServiceDay lifecycle service (lazy creation + `planned → open` transition — the model and its documented behavior exist now in `app/models/service_day.py`, the service function doesn't yet).

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
pytest tests/ -v
```

## Design notes worth knowing before extending this

- **UUID primary keys**, generated app-side (`uuid.uuid4()`), not DB-side — no `pgcrypto` extension dependency.
- **`business_date` is not the calendar date.** `Venue.timezone` + `Venue.business_day_boundary` (default 04:00) define it; the resolution logic belongs in step 8, not written yet — don't compute business_date ad hoc elsewhere once that service exists.
- **`Staff.user_id` is nullable on purpose.** Line staff don't need a login.
- **`MenuItem` and `Recipe` are different tables**, linked by `MenuItemRecipe` — a burger can reference a patty recipe and a sauce recipe.
- **`AuditEvent` is append-only.** Always write it through `audited_transaction`, never with a separate `session.add()` + its own commit — that's exactly the pattern the atomicity requirement exists to prevent.
- **Login is magic-link only — no passwords anywhere.** `POST /auth/request-link` finds-or-creates the `User` by email; that's also how a brand-new owner "signs up" (there's no separate registration endpoint) — `POST /organisations` is the first real action they take once logged in.
- **Organisation/Venue creation and the Membership it creates commit as one transaction.** See `create_organisation_with_venue`'s docstring for why the entities being audited have to be flushed (not committed) before `audited_transaction` opens — worth reading before adding another "create several rows atomically" endpoint.
- **Role checks always hit the DB, never the token.** `require_membership` looks up `Membership` fresh on every request. Don't "optimize" this by putting role/venue claims in the JWT — that would mean a demoted or removed user keeps their old access until the token expires.
- **A 403 from `require_membership` never distinguishes "wrong role" from "venue doesn't exist" from "belongs to someone else"** in a way that leaks across tenants — see `tests/test_tenancy.py::test_venue_scoped_route_403s_a_nonexistent_venue_same_as_someone_elses`.
