# Mise — frontend

A mobile-first React + TypeScript PWA for the Mise API (`../`) — full UI parity with all 11 backend epics. Built as a phone-first tool for a head chef standing in a kitchen, not a desktop admin panel: one-handed use down to 390px width, dark/high-contrast by default, "never color alone" (every status Badge pairs a color with a distinct glyph — •▲✕✓ℹ), and every tile on the daily Chef Brief links straight into the module it's summarizing.

## Stack

- **React 19 + Vite 8 + TypeScript** (strict — `verbatimModuleSyntax` needs `import type` for type-only imports, `noUnusedLocals`/`noUnusedParameters`, `erasableSyntaxOnly` rules out `enum` in favor of string-literal unions, matching the backend's own Python `str` enums field-for-field).
- **Tailwind CSS v4** via the `@tailwindcss/vite` plugin — theme tokens live as CSS custom properties in `src/index.css` (`--color-accent`, `--color-surface`, …), no separate `tailwind.config`/`postcss.config`.
- **`vite-plugin-pwa`** — installable, offline-app-shell PWA. `navigateFallbackDenylist` excludes `/^\/api\//` so a stale service worker can never serve a cached page in place of a live API call (the API itself is same-process on the LAN in a pilot deployment, not a relative `/api/*` path, so this is a belt-and-braces guard, not the primary defense — see CORS below).
- **`react-router-dom` v7**, **`@tanstack/react-query` v5**, **`date-fns` v4**.

## Running it

```bash
npm install
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000
npm run dev             # http://localhost:5173
```

The backend needs `CORS_ALLOW_ORIGINS` (in its own `.env`) to include whatever origin this dev server runs on — it defaults to `http://localhost:5173,http://127.0.0.1:5173`, so a stock `npm run dev` on the default port needs no backend config change. See `../app/core/config.py`.

`npm run build` runs `tsc -b && vite build` — a type error fails the build, which is how most of the bugs in "Bugs found and fixed by smoke testing" below were actually caught in the end (the ones the compiler couldn't see needed a live backend, which is why that section exists).

## Architecture

- **`src/api/types.ts`** — a hand-written, 1:1 mirror of every backend Pydantic schema and Python `str` enum, across all 11 epics. No codegen: for a single-developer build against a backend that's already fully spec'd and tested, a direct mirror is easier to keep honest by eye (grep the schema file, grep this file) than to debug a generator's output against.
- **`src/api/client.ts`** — one `request<T>()`/`requestBlob()` wrapper plus a namespaced `api` object (`api.auth`, `api.roster`, `api.prep`, …) mirroring the backend's route file names exactly, one method per endpoint. Verified against a full grep of every `@router.get/post/patch/delete` in `app/api/routes/*.py` — every backend endpoint has a corresponding client method.
- **`src/auth/AuthContext.tsx`** — magic-link auth (no passwords, matching the backend's own design decision). Tracks `currentVenueId` (a User can hold Memberships at more than one Venue) and derives `currentRole` from it. `MANAGEMENT_ROLES` / `PREP_EXECUTION_ROLES` / `OWNER_ONLY` constants and the `useHasRole()` hook mirror the backend's own role tiers in `app/api/deps.py` exactly.
- **`src/components/RoleGate.tsx`** — hides UI the current role's own token would get a 403 from anyway. **This is UX only.** The backend's `require_membership(...)` is the only real enforcement point; nothing here is a substitute for it, and every page's comments say so at the point of use.
- **`src/hooks/useCurrentServiceDay.ts`** — "today" for kitchen-ops purposes is never `new Date()` on the client. It's always read from `GET /venues/{id}/service-days/current` (lazily creates, never 404s), mirroring the backend's own `resolve_business_date` single-source-of-truth rule (a dinner service ending 1am is still the prior business_date).
- **`src/app/Shell.tsx`** — the mobile chrome: a slim top bar (venue switcher), a 5-tab bottom nav sized for a thumb, and a floating Quick Capture button (the one action a chef needs mid-service from any screen, not gated behind a 6th nav slot).
- **`src/pages/<epic-area>/`** — one folder per epic's UI surface (`chef-brief/`, `roster/`, `prep/`, `orders/`, `capture/`, `handover/`, `kitchen-memory/`, `more/` for the Epic 1/10/11 admin screens that don't need their own nav tab).

## What's built

Full parity with all 11 backend epics:

- **Epic 1** — magic-link login/verify, org+venue onboarding, staff-link public shift view (no login), and admin screens for staffing (stations/staff/skills/coverage rules), catalog (suppliers/ingredients/menu items/equipment), venue settings, and invites.
- **Epic 2/3** — Kitchen Roster (week view as day-by-day cards, not a 7-column grid — that can't work at 390px) with publish/cancel/copy-week/roster-PDF-download, folded together with per-shift attendance logging and history.
- **Epic 4** — today's Prep list grouped by station (status edits gated to `PREP_EXECUTION_ROLES`, narrower than management), template admin, apply-template/carry-forward, and a deliberately chrome-free printable view.
- **Epic 5** — Supplier Orders: add-or-merge a line onto a draft PO, per-line quantity correction, send, mark delivery (full/partial), delivery issues.
- **Epic 6** — Quick Capture: free-text capture, then a type-specific confirm form (restock/eighty-six/equipment-issue) or reject, matching whichever entity the backend's classifier proposed.
- **Epic 7** — Handover: start-of-day "Start service" action (see below), close-day with a note, the six auto-populated item categories with per-item include/exclude, reopen, handover PDF download.
- **Epic 8** — Chef Brief, the default landing view: coverage gaps, rostered staff, priority prep, carried-forward tasks, approaching order cutoffs, open equipment issues, menu availability, yesterday's handover — every tile links into its own module.
- **Epic 9** — Kitchen Memory: cross-entity search, recipe version history (a "recipe" is genuinely versioned — editing means creating version N+1, never mutating a past version), menu-item-to-recipe linking, equipment issue history.
- **Epic 10** — Notifications admin: manual "run checks now" trigger plus the resulting sent-notification list (the backend has no scheduler yet, so this manual trigger is the only way to fire the same checks a cron job would).
- **Epic 11** — Pilot metrics: minutes-saved-per-week, incident log, the owner-only pilot pay-decision, and a full event feed.

## Known limitations

- **Client-side role gating is UX only** (see `RoleGate.tsx` above) — worth repeating at the top level, not just inline.
- **Shift date/time inputs assume the browser and the venue share a timezone.** `datetime-local` values are converted with `new Date(value).toISOString()`, which uses the *browser's* local timezone to interpret the wall-clock value typed in. A chef scheduling shifts from a different timezone than the venue would get the wrong instant. The backend's `resolve_business_date` is timezone-correct against `Venue.timezone`; this one input path isn't yet.
- **Quick Capture's parser can only match against catalog entries that already exist.** "We're out of salmon" comes back `unparsed` if no Ingredient named (or fuzzy-matching) "salmon" exists yet at that venue — correct behavior per the backend's rule-based classifier, but worth knowing before assuming a capture "isn't working."
- No offline queueing — the PWA installs and the app shell is cache-first, but every data operation still needs a live connection to the API; there's no write-behind queue for a dead kitchen wifi moment.

## Bugs found and fixed by smoke testing

`tsc -b` catches type errors but can't catch a request that's well-typed and still wrong at runtime. These four were only found by driving the built app against a live backend end-to-end (Playwright + Chromium) and following every write path, not just loading every screen:

1. **Backend had no CORS configuration at all.** A separate-origin SPA (this app on `:5173`, the API on `:8000`) can't call the API from a browser without it — every request failed silently until `CORSMiddleware` + a `cors_allow_origins` setting were added to the backend (`app/main.py`, `app/core/config.py`, `tests/test_cors.py`). Without this fix, *none* of what follows would have been reachable to test.
2. **Onboarding never navigated away after creating a venue.** `CreateOrganisationPage` called `refreshMe()` on success but never `navigate()` — a brand-new owner would sit on the "Set up your kitchen" form forever despite being fully signed in with a membership. Fixed by navigating to `/` (and setting the new venue current) once `refreshMe()` resolves.
3. **A stale-`useState`-default bug in three different "pick from a list" forms** (`PrepTemplatesPage`'s add-item form, `OrdersPage`'s add-line form, `RosterWeekPage`'s create-shift form, `StaffingAdminPage`'s add-skill form): each initialized a `<Select>`'s backing state to `''` and only *displayed* the first real option as a fallback (`value={stationId || stations[0].id}`). If the form mounted before its options had finished loading, the display fallback kept showing correctly, but the underlying state variable stayed `''` forever — so submitting with the (visually selected) default option sent an empty id and the backend correctly 422'd it. Fixed by deriving one `effective*Id` value used for *both* the Select's `value` and the submitted payload, everywhere this pattern occurred.
4. **The "add order line" form allowed submitting without a delivery date or an order cycle**, which the backend rejects (a draft PO's identity is `(venue, supplier, required_delivery_date, order_cycle)` — supplier alone isn't enough to tell two concurrent draft orders apart). The form only exposed the date field as optional; fixed by adding an "order cycle" field and disabling submit until at least one of the two is set, so the chef sees this before submitting instead of a raw 422.
5. **There was no way to open a service day from the UI at all.** A `ServiceDay` is lazily created `planned` and stays that way until the explicit, audited `open_service_day` step — but closing it into a Handover requires `open`, not `planned`. The API client already had `serviceDays.start()` wired up, but no page ever called it, so the entire Handover flow was unreachable from a fresh day. Fixed by adding a "Start today's service" action to the Chef Brief page (management roles only, shown only while the day is still `planned`).

All 329 backend tests pass (326 pre-existing + 3 new CORS tests) and the frontend type-checks and builds cleanly; the full flow — login → onboarding → staffing/catalog setup → roster/shift/attendance → prep template/apply → supplier order (line → send) → recipe/menu-item linking → start service → close handover → PDF downloads — was driven end-to-end against a live Postgres-backed API as part of this pass.
