# Phase 1 progress as of Nov 5, 2026: what's built and how it fits the teammate's plan

Written Nov 5, 2026. **Base plan:** `docs/planning/feature-map-and-architecture.md` (stages 0A–12). For each stage, this document says what Phase 1 already provides, where it lives in the code, what is left to build, and what to watch out for. Paths are relative to the repo root. Legend: ✅ built · 🟡 partly built · ❌ not built.

## 1. Rules every new feature should follow

Phase 1 set these patterns. New code that follows them gets live updates, safety checks and CI coverage for free.

| Rule | How Phase 1 does it | Where |
|---|---|---|
| Money is whole cents | `Cents` type; `"12.34"` strings only at the PayPal boundary (`to_paypal_value` / `from_paypal_value`) | `src/trippilot/contracts/money.py` |
| Only `payments` talks to PayPal | Other code calls `get_paypal_gateway()` and the `PayPalGateway` interface; CI fails if any other package imports the client, token cache, vault store or `cryptography` | `importlinter.ini`, `tests/unit/test_import_boundaries.py`, `src/trippilot/contracts/paypal.py` |
| Every PayPal write has a request ID | Each gateway method takes `request_id`; retries reuse it | `src/trippilot/payments/client.py` |
| Money calls are recorded | `append_ledger_entry(...)` writes `ledger_entries`; database triggers reject UPDATE and DELETE | `src/trippilot/payments/ledger.py`, migration `0004_payments.py` |
| A trip's data is only for its members | `get_trip_view` / `require_organiser_trip` answer **404** (not 403) to non-members, so trip IDs can't be probed | `src/trippilot/trips/service.py` |
| Changes go live through the event log | Call `append_trip_event(db, trip_id, type, payload)` in the same transaction as the change, then commit | `src/trippilot/realtime/events.py` |
| Handlers commit explicitly | Call `await db.commit()` in the handler; the automatic commit can run after the response is sent | 01-20 |
| Schema changes are hand-written SQL migrations | Add `0005_...py` under `src/trippilot/db/alembic/versions/`; CI checks there is exactly one head | 01-19 |
| Slow work goes to the worker | procrastinate tasks; one image, started as web or worker | `src/trippilot/jobs/app.py`, `jobs/tasks.py` |
| The frontend uses the generated client | `scripts/dump_openapi.py` → `npm --prefix web run gen:api` → `web/src/lib/api.ts` (`unwrap`, `ApiError`) | 01-23 |
| Return JSON, not empty bodies | The SPA's `unwrap` treats an empty body as an error, so write endpoints return 200 with JSON, not 204 | 01-05 |

> **In plain terms:** these are the house rules. For example, "changes go live through the event log" means you never push updates to browsers yourself. You save a small "something changed" note in the database, and Phase 1's plumbing delivers it to every open screen.

## 2. Stage by stage

### 0A · PayPal feasibility · 🟡

- **Proven in the sandbox:** Log in with PayPal; saved PayPal (vault); holds, partial capture and void (three buyers in one run, 01-14); Pay Later on a hold (01-11); verified webhooks (01-13). Payouts were tested on Oct 22 with a standalone script, before Phase 1. Scripts are in `scripts/spikes/`, results in `docs/design-notes.md`.
- **Not tested:** their target route, where a member pays the leader's personal account and TripPilot verifies it. Our research found no normal API for it: webhooks only cover payments made through our own app, and reading another account's history needs partner access. This is the first thing to settle under their plan.
- **Watch out:**
  - A hold is guaranteed for 3 days (create time + 72h), even though PayPal reports a 29-day expiry.
  - The renewal test (01-18 / 01-26) hasn't run yet. Two test holds are waiting for it (`3HJ189595J804324R`, `21G42554211627257`) and must not be voided or captured. They expire Nov 26.

### 0B · Travel data · 🟡

- **Phase 1:** a Duffel flights adapter spike (`scripts/spikes/duffel_flights.py`). It works, but only with the fake airline (ZZ) and Duffel sells tickets, so it was dropped. Duffel Stays was refused (403).
- **To build:** search, places and routes adapters. SerpApi/HasData free tiers have been checked by research only, with no code yet.

### 1 · App foundation · ✅

- **How it's built:**
  - Where the backend is assembled: `create_app()` in `src/trippilot/app.py`. It loads the settings, adds the security check (the Origin check below), and plugs in each feature's set of URLs ("routers"): health, sign-in, trips, PayPal, live events, admin, plus the demo personas only when demo mode is on. On startup it also waits for the database and starts the live-update listener. *In plain terms:* each feature keeps its own URLs in its own folder, and `create_app()` is the one place that wires them into a single app. A new feature (say chat) writes its own router and adds one `include_router` line here.
  - Typed configuration: `settings.py` (pydantic-settings). It refuses to start staging or production with a missing secret.
  - Async SQLAlchemy on psycopg 3: `db/engine.py`.
  - Startup database wait (up to 60 s): `db/startup.py`.
  - Migrations run once under a database lock in Render's pre-deploy step: `db/migrate.py`.
  - `GET /api/health`: a real database query plus the worker heartbeat (`health.py`).
  - Structured JSON logs with secrets redacted: `log_config.py`.
  - One Docker image (`Dockerfile`, `docker-compose.yml`). Render blueprints: `render.yaml` (staging) and `render.production.yaml`.
  - CI: `.github/workflows/ci.yml`. Release image per merge: `release.yml`. Production only through an approved `promote.yml` run.
- **Sign-in:**
  - Log in with PayPal (OIDC code exchange): `auth/paypal_login.py`.
  - Sessions are a random 256-bit cookie, stored only as a hash, sliding for 30 days: `auth/sessions.py`.
  - `CurrentAccount` / `OptionalAccount` dependencies: `auth/deps.py`.
  - An Origin check on every write (CSRF): `auth/csrf.py`.
  - Demo personas, mounted only when `DEMO_MODE` is on: `demo/cast.py`, `demo/router.py`.
- **Watch out:**
  - On Windows, start uvicorn with a SelectorEventLoop; psycopg refuses the default Proactor loop.
  - A request without Origin or Referer headers skips the CSRF check.
  - `/api/auth/paypal/start` has no rate limit.

### 2 · Trips, profiles, invites, permissions · 🟡

- **Built:**
  - Tables: `trips`, `members` (role, status), `invites` (stores only a hash of the token). See `trips/models.py`.
  - The invite token is derived with HMAC from `INVITE_SECRET` and the invite id. `join_via_invite` runs under a row lock on the trip, with a 12-member cap and a per-process rate limiter. See `trips/invites.py`.
  - Removal sticks across link resets.
  - Routes: `POST/GET /api/trips`, `/api/trips/{id}`, `/invite`, `/invite/reset`, `/joining`, `/leave`, `/members/{account}/remove|readd`, `GET /api/invites/{token}` (preview), `POST /api/invites/{token}/join`.
  - Accounts: `accounts` has nickname and avatar; `PATCH /api/me` edits them.
- **To build:** a `TravelProfile` (origin, interests, diet, pace) and private preference fields.
  - Add a new table with its own migration, rather than more columns on `accounts`.
  - Filter private fields in the service layer, so they never reach another member's response.
- **Watch out:**
  - Persona accounts are shared rows, so `PATCH /api/me` answers 403 for them. Profile editing needs a demo-safe path.
  - The invite rate limiter keys on the last `X-Forwarded-For` entry and lives in memory, per process.

### 3 · Chat, live updates, `/plan`, private concerns · 🟡

- **Built (the hard part), Oct 28.** Plan 01-05 added the event log; 01-09 added the stream and the live trip page. Both were merged to `main` in PR #3 the same day.
  1. `append_trip_event` inserts a `trip_events` row and sends `pg_notify` with only the id. The payload limit is 8000 bytes, so the listener re-reads the row.
  2. Each web process holds one LISTEN connection (`realtime/listener.py`) and fans events out through `TripHub` (`realtime/hub.py`).
  3. `GET /api/trips/{id}/events` (`realtime/router.py`) streams them as SSE and replays from `Last-Event-ID` after a reconnect.
  4. `web/src/features/trips/useTripEvents.ts` refetches React Query data when an event arrives.
- **To build:** a `messages` table plus a `message.created` event; a `/plan` button that queues a job; private concerns.
- **Watch out, important:**
  - **Every member of a trip receives every trip event.** Never put private data (concerns, budget caps, profile fields) in an event payload. Send a bare "changed" signal and let each member refetch their own filtered view.
  - Inside psycopg's `notifies()` loop, only queue ids. Loading rows there deadlocks the connection.
  - Release the database session while a stream is open. Otherwise a few viewers exhaust the 5+5 connection pool.
  - Notifications sent while the listener is down are lost. The hub resyncs streams after a reconnect.
  - The SSE update is the flaky step in the Playwright test.

> **Example:** if Ana's private concern ("I can't afford the boat tour") were put in an event, every member's browser would receive it, even if the screen hid it. So the event just says "concerns changed", and only Pilot's summary ever leaves the server.

### 4 · Plan model, cents, day map · 🟡

- **Built:** the `Cents` type and the PayPal conversions, tested.
- **To build:** `PlanVersion`, `PlanItem`, `Participation`; the share calculator; the day map; a budget summary.
  - Put the share calculator in a new pure module (e.g. `src/trippilot/core/shares.py`) with property tests: shares add up exactly, and the same input always gives the same answer.
  - Example: $1,000.00 across 3 people is 333.33 + 333.33 + 333.34.

### 5–9 · Pilot, decisions, replanning, transport, bookings · ❌

Not started. Reusable pieces:
- **Pilot:** jobs go to the worker; progress goes through `append_trip_event`; the "no money tool" rule is already enforced by `importlinter.ini`. Add a `pilot` contract to it, so the AI package can never import `payments`.
- **Bookings (stage 9):** needs private file storage for confirmations; there is none yet.

### 10 · Contributions and PayPal · 🟡

- **Built:**
  - The `PayPalGateway` interface: setup and payment tokens, vaulted and normal AUTHORIZE orders, authorize, get, reauthorize, capture, void, webhook verify/create/list, login exchange, userinfo.
  - `FakePayPal` for tests (`payments/fake.py`). Token cache that revokes and retries once on 401/403 (`payments/token_cache.py`).
  - Encrypted vault store: `payments/vault_store.py` (MultiFernet, keys in `VAULT_KEYS`). Vault routes: `/api/paypal/vault/*`.
  - Pool buyers for simulated friends: `payments/pool.py`.
  - Webhooks: verified and stored once in `webhook_events`, unique on PayPal's event id. A worker task only records them (`payments/webhooks.py`, `payments/tasks.py`).
- **Not built:**
  - **payouts, refunds and pay-now (CAPTURE) orders** are not in the client yet;
  - reconciliation (webhooks are recorded but not acted on);
  - contribution records;
  - their direct member-to-leader route.
- **Watch out:**
  - PayPal keeps one saved token per payer per app. Saving the same sandbox payer for a second person silently deletes the first person's token.
  - A 403 on a vaulted order can mean the token is gone, not a permission problem. Use `scripts/spikes/three_buyer_holds.py --diagnose`.
  - Webhooks arrive out of order (a void before its create). Always confirm with a GET before acting on one.
  - Removing a saved PayPal isn't blocked while a hold is open. Add that check before any money flow.
  - After changing app features in the PayPal dashboard, revoke the cached access token, or the old permissions stay.

### 11 · Expenses and settlement · ❌

Not started. The ledger records money moves, not expenses. Their "accounting" module (expenses, allocations, settlements) is new tables. Settle-up by PayPal would need the payouts call added in stage 10.

### 12 · Dashboard and demo hardening · 🟡

- **Built:**
  - Demo personas: one person can play the whole group.
  - A "Sandbox — no real money" banner on every route (`web/src/components/SandboxBanner.tsx`).
  - Loading, empty and error states (`SkeletonList`, `EmptyState`, `ErrorRetry`).
  - Brand tokens and shadcn/ui components (`web/src/components/ui/`).
  - A Playwright end-to-end test (phone viewport; switch it to desktop).
- **To build:** the dashboard, demo reset, quota fallbacks and judge logins (`JUDGE_LOGINS` is empty; deferred).

## 3. Hosting and tooling traps

- **Render env vars:** changing one needs a deploy, not a restart. On staging, set it and then run `release.yml`. On production, re-promote the running commit.
- **Production deploys:** only through `promote.yml`, with approval. Never use Manual Deploy or Sync. Tick the `production` box before approving, or the approval doesn't save.
- **Cost:** staging is suspended between uses, and whoever resumes it suspends it again. Production is on from Nov 5 to Dec 21. There's no spend alert on the $50 credit, so check billing by hand.
- **Deploy race:** web and worker deploy together, so the worker can start before migrations finish. Keep migrations backward compatible.
- **Generated API types:** `web/src/lib/api-types.ts` is gitignored. Run `uv run python scripts/dump_openapi.py` and `npm --prefix web run gen:api` before a frontend typecheck.
- **TypeScript:** pinned to 6.0.3, because 7.x breaks openapi-typescript.
- **`gh` default repo:** it points at another repo. Always pass `--repo RishzG/TripPilot-app`.
- **Pending security step:** staging `VAULT_KEYS` and `INVITE_SECRET` were exposed in a transcript, and rotating them was advised. There's no key-rotation script yet.

## 4. Suggested way forward (on their plan)

1. **Mark stage 1 done.** Close stages 2 and 3 by adding the travel profile, chat, the `/plan` button and private concerns on top of the existing trips and live-update code.
2. **Build stage 4 next:** the plan model, the pure share calculator, and the map.
3. **Settle 0A now, in parallel.** Decide whether their direct route can be verified at all; if it can't, choose the fallback with the team. Stage 10 depends on this.
4. **Before stage 10:** add payouts, refunds and pay-now orders to the PayPal client; add reconciliation; block removing a saved PayPal while a hold is open.
5. **Keep the Phase 1 rules (section 1) for every new module,** especially the event-payload privacy rule.
