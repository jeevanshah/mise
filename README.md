# Mise API

Epic 1 (Foundation, Onboarding & Audit) — **complete**, all 9 steps. Epic 2 (Kitchen Roster) — **complete**. Locked Rev 4 spec. FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL.

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

**Epic 1 is done.**

## Epic 2 — Kitchen Roster

The service-period question (lunch/dinner/events as a separate `ServicePeriod` vs. one `ServiceDay` per day) is **confirmed**: no `ServicePeriod` for v1, coverage stays keyed by day-of-week only — the documented default in the epics doc. `app/services/roster_service.py` + `app/api/routes/roster.py`:

- **Shift create** (`POST /venues/{id}/shifts`) — one Shift = one Station × one Staff member for a time span; a station/day cell with several people on it is several Shift rows. Rejects (409) a Staff member being scheduled into two overlapping Shifts, **including across different Stations** — checked before saving. `business_date`/`ServiceDay` is resolved and lazily created from `start_at` (same `resolve_business_date` as Epic 1) but stays `planned` — creating a future Shift is "first referenced," not an operational write, so it doesn't open the day.
- **Publish** (`POST /venues/{id}/shifts/{id}/publish`, or `POST /venues/{id}/rosters/publish-week` for a whole week at once) — `draft → published`, idempotent (republishing is a no-op, no duplicate link/notification). Issues a signed `StaffLink` scoped to that one Shift and queues a notification per affected Staff member — no email provider exists yet (Epic 10), so this is a real, traceable `AuditEvent` stand-in today (`roster.notification_queued`) and the raw link token is returned directly in the response outside `ENVIRONMENT=production`, exactly like `auth_service`'s `dev_token`.
- **Cancel** (`POST /venues/{id}/shifts/{id}/cancel`) — idempotent; revokes any `StaffLink` issued for that Shift in the same transaction, since a signed link is only ever valid for a live Shift.
- **Copy last week** (`POST /venues/{id}/rosters/copy-week`) — duplicates every non-cancelled Shift from one week into another as fresh `draft` Shifts (never inherits `published`), creating target `ServiceDay`s as needed. Preserves local wall-clock time-of-day (not the raw UTC offset) via the venue's own timezone, so an overnight 6pm–1am shift still crosses midnight the same way after the copy. Validated in two passes — every prospective new Shift is checked for overlap against existing Shifts *and* against the rest of the batch before anything is written, so a conflict aborts the whole copy with nothing created.
- **StaffResponse is a genuinely separate state machine from Shift.status** (locked AC) — cancelling or republishing a Shift never touches it. Staff respond confirm/decline either logged in (`POST /venues/{id}/shifts/{id}/respond`, only if their own `Staff.user_id` is the one assigned) or via the signed link with no login at all (`GET /staff-links/{token}` to view, `POST /staff-links/{token}/respond` to answer) — the link 404s the same way for unknown, expired, revoked, or already-cancelled-Shift tokens, so a guess can't distinguish which.
- **Coverage warnings** (`GET /venues/{id}/service-days/{business_date}/coverage-warnings`) — fires when Shifts (draft or published, not cancelled) scheduled against a Station and overlapping a `StationCoverageRule`'s day/time window fall below that rule's `minimum_staff`; a shift entirely outside the window doesn't count.

## Epic 3 — Attendance & Coverage

`app/services/attendance_service.py` + `app/api/routes/attendance.py`. `AttendanceEvent` is an append-only log — nothing is ever updated or deleted. "Current attendance" for a Shift is always a derived read (the latest event by `recorded_at`; no event = `null`/"expected" — never stored), so the live status and the full history can never drift apart.

- Chef logs an event any time (`POST /venues/{id}/shifts/{id}/attendance-events`, `MANAGEMENT_ROLES`) — no cap on corrections.
- Staff logs **exactly one** event for their own Shift via the signed link (`POST /staff-links/{token}/attendance-events`, no login) — a second attempt is a 409, `DuplicateStaffCheckIn`.
- A later event — chef or staff — wins for the displayed "current" status by `recorded_at`; the earlier one is retained untouched in the history, never overwritten.
- `GET /venues/{id}/shifts/{id}/attendance` (derived current) and `.../attendance-events` (full history) — any Membership can read.
- No GPS/biometric/location field anywhere on `AttendanceEvent` — verified by a test that walks the model's columns, not just left out by omission.

## Epic 4 — Prep Plan

`app/services/prep_service.py` + `app/api/routes/prep.py`. Depends only on Epic 1 (not Epic 2) — a PrepTask is keyed to a `ServiceDay`, not a `Shift`.

- `PrepTemplate` + `PrepTemplateItem` — a reusable, ordered `{station, item, quantity, priority}` list. Applying a template (`POST /venues/{id}/service-days/{business_date}/prep-tasks/apply-template`) **copies** each item's fields onto a fresh `PrepTask` — nothing references the template live, so editing a task afterwards never touches the template and vice versa.
- `PrepTask.status` (`not_started`/`in_progress`/`done`/`blocked`) is updated only by **Head Chef or Sous Chef** — a new, narrower `PREP_EXECUTION_ROLES` constant (`app/api/deps.py`), deliberately different from `MANAGEMENT_ROLES`: this is kitchen-floor execution, not venue configuration, and the locked AC names exactly those two roles.
- **Carry forward** (`POST .../prep-tasks/carry-forward`) creates next-day `PrepTask`s from anything not `done`, marks the originals "carried" by setting `carried_to_task_id` (there's no separate status value for it), and is idempotent — re-running it for the same pair of days does nothing the second time, so the chain only ever extends one hop at a time and never branches or duplicates. `carry_count` is the "day-count badge," climbing by exactly one per hop.
- Printable list (`GET .../prep-tasks/printable`) is a deliberately narrower schema — station name, item, quantity, unit, priority, status — with none of the internal bookkeeping fields (`template_item_id`, `carried_*_task_id`) a chef-only admin view would show.

## Epic 5 (Supplier Orders) is next per the locked build order.

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
pytest tests/ -v     # 149 tests
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
- **`MANAGEMENT_ROLES`** (`app/api/deps.py`: owner, ops_manager, head_chef) gates every "configure the venue" action (stations, staff, coverage rules, suppliers, ingredients, menu items, equipment, shifts/roster). sous_chef/line_staff can read but not configure. Reuse this constant rather than redefining the role set per router.
- **A duplicate create is a 409, never a silent update.** StaffSkill, StationCoverageRule, and inviting an existing Membership all follow this — see each service module's `Duplicate*` exception classes.
- **A signed `StaffLink` is scoped to exactly one Shift**, not "all of this Staff member's shifts" — each publish issues its own link, the same way Epic 3's check-in links will. That's what makes "invalidated automatically if the underlying Shift is cancelled" a precise, live-checked rule (see `roster_service.resolve_staff_link`) rather than a cached flag.
- **`Shift.start_at`/`end_at` are timezone-aware instants, not a (date, time-of-day) pair.** A dinner shift can run 18:00–01:00; overlap checks and coverage-window comparisons all work in absolute instant arithmetic, converting to the venue's local timezone only where the locked spec's rules are actually stated in local time (coverage windows, "copy last week"'s wall-clock preservation).
