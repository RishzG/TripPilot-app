# Implementation progress · November 6, 2026

**Historical implementation log.** Current status, bug notes, manual checks and teammate work
streams are maintained in [docs/progress](../progress/README.md). The latest user-requested UX
uses dedicated Chat and Plan views and removes group-management shortcuts from Trip overview;
earlier side-by-side layout notes below record the intermediate implementation.

The user authorized starting the recorded feature plan on November 6. Implementation checkout:
`D:/Projects/TripPilot`, remote `https://github.com/RishzG/TripPilot-app.git`, branch
`codex/group-workspace`, based on `main` at `a1d5eef`.

## Delivered: trip travel preferences (stage 2)

A signed-in active member can open a trip, save their starting city, interests, pace, optional
USD trip budget and dietary notes, reload and recover the saved values. Another active member
can see only their city, interests and pace, updated through the existing event stream.

- `0005_travel_profiles` adds a separate profile table keyed by trip and account, with a foreign
  key to membership. Identity/profile appearance and payment tables are unchanged. This also
  keeps a shared demo persona's preferences isolated between demo trips.
- `GET /api/trips/{trip_id}/preferences` returns the caller's `mine` profile and an explicit
  allowlist of shared fields for active `members`. Budget and dietary notes are owner-only.
- `PUT /api/trips/{trip_id}/preferences/me` replaces only the authenticated member's profile.
  It uses the trip lock shared by membership mutations, upserts the profile, appends an event,
  and explicitly commits before returning JSON. Repeated saves update one profile row.
- Defaults are empty city/interests/diet, balanced pace, and an unspecified budget. Fields are
  optional and can be cleared. Budget zero and unspecified are distinct; the backend accepts
  integer cents only, from 0 through 100,000,000. Text is trimmed and length-bounded.
- `preferences.updated` contains `{}`. Browsers refetch their own filtered projection on this
  event, stream reconnect, membership changes, and returning to the tab. Private values never
  enter the event log. Removed members cannot read or write preferences.
- The trip page includes the editable preferences card and an expandable group summary.
  Failed saves retain input, duplicate submission is disabled while pending, and budget entry
  converts decimal dollars to integer cents without floating-point multiplication.

Private fields are not yet sent to any model. The future Pilot context/privacy policy must be
implemented explicitly before using them. No external model/search/payment provider is called
by this feature. Travel profile defaults are implementation choices, not confirmed group facts.

## Verification

- Full backend suite: **484 passed**, including 14 new preference integration cases. Ran against
  a fresh isolated PostgreSQL 18 cluster on loopback; no hosted database or sandbox payment used.
- Full frontend suite: **296 passed**. Covers exact-cent input, optional/zero budget, invalid
  input, private/shared rendering, save retries, loading retries and event invalidation.
- Ruff lint and format checks, strict mypy, TypeScript typecheck, frontend build and single
  Alembic head (`0005_travel_profiles`) pass. Biome 2.6.3's supported WebAssembly API reports
  zero errors/warnings on changed frontend files; Windows initially blocked the native binary.
- Desktop browser verification: **2 passed**, at **1366 x 768** and **1920 x 1080**. Two real
  browser sessions sign in, create/join a trip, save preferences through the UI, reload and
  recover private values, and observe public changes through SSE without a reload. The other
  member's API response excludes the private values. No page exceptions or horizontal overflow.
  Screenshots are generated in the ignored `web/test-results/` folder and visually reviewed.

To repeat against a local demo-mode stack (PostgreSQL, migrations and API running with the built
frontend, `PAYPAL_MODE=fake`, `DEMO_MODE=true`):

```sh
uv sync --frozen
npm --prefix web ci
uv run python scripts/dump_openapi.py
npm --prefix web run gen:api
npm --prefix web run build
uv run pytest -q
npm --prefix web test -- --run
npm --prefix web exec -- playwright install chromium
npm --prefix web run e2e -- --project desktop-laptop --project desktop-wide
```

The browser suite uses `http://localhost:8000`. On Windows, the API's running event loop must be
a SelectorEventLoop for psycopg; setting the policy alone is insufficient when a launcher supplies
its own Proactor loop factory. The test fixture derives a separate database ending in `_test`.

The build reports a bundle-size advisory for the app entry chunk. No deployment was performed.

### Follow-up: summary refresh after Save

The user reported that the group summary still displayed the empty starting-city/interests
defaults after saving. Save now returns the complete caller-filtered preferences projection,
and the client cancels an older in-flight read and replaces the cached projection directly.
The form adopts the server's normalized saved values. A successful save no longer depends on
a follow-up GET to update the summary. Demo-persona sign-in also clears `trip-preferences`
from the previous visitor's cache.

A regression test asserts that city, interests and pace update immediately with no second GET.
The 14 preference API tests and strict typing pass; the full frontend suite has 296 passing
tests. Desktop tests additionally check the saving member's own summary before reloading.

## Progress and next slice

### Empty-state clarity and deleting an unused workspace

- Example hints in city, interests and budget now start with `Ex.` and use light italic text.
  They are placeholders; an untouched field is still an empty saved preference.
- The organiser can delete a workspace when no other active member remains. The trip view
  exposes `can_delete`; `DELETE /api/trips/{trip_id}` verifies organiser access and checks all
  active membership under the same row lock used by joins. Left/removed members do not block
  deletion. It returns JSON after commit.
  Database cascades remove the unused workspace's preferences, invite links and event rows.
- The trip page requires an explicit confirm, supports cancellation, reports a join conflict,
  and returns home after success. Delete stays visible for organisers and is disabled with an
  explanation while other active members remain; it becomes enabled after they leave or are removed.
- Negative budget input now explicitly reports `Budget cannot be negative.`; too many decimal
  places still receive the decimal-format error.
- Verification: 49 deletion/invite integration tests and 300 frontend tests pass;
  strict backend typing, frontend build, and four desktop browser tests cover the changed flow,
  including a specific negative-budget error and deletion after the last other member leaves.
- Follow [the manual test checklist](manual-test-group-workspace.md) for empty-field behavior,
  persistence, privacy, live updates and unused-workspace deletion.

This completes the missing trip-scoped travel-preferences portion of stage 2, not all of stage 2
or checkpoint A/B. Existing trip/invite/auth/event foundations remain in use. General trip
editing and trip dates/timezone preferences still need implementation.

## Delivered: persisted group chat (stage 3, first slice)

- `0006_trip_messages` stores plain-text messages with a captured author name, aware timestamp,
  trip membership ownership, ordered history index and a unique sender/trip/client-message ID.
- `GET /api/trips/{trip_id}/messages` returns the latest 30 messages in chronological display
  order; `before` and `limit` fetch older pages (maximum 100 per page). Cursors are bounded.
- `POST /api/trips/{trip_id}/messages` accepts 1–4,000 trimmed characters and a client UUID.
  It checks current membership under the trip lock, records one message and a `message.created`
  event, then commits. The event contains only the message ID. Retrying the same text/ID returns
  the same message; reusing the ID for different text returns 409. Caller-supplied authors are
  rejected. Removed/left members cannot read, send or replay an earlier send attempt.
- The desktop trip page has a group chat panel, author/timestamps, multiline composer,
  explicit Send button, empty/error/loading states, older-history loading, and a retained draft
  on failure. A retry uses the same UUID, including when the server committed but its response
  was lost. Text is rendered as text; markup and `/plan` do not execute anything.
- Chat refetches on committed message events, reconnect, returning to the tab and membership
  changes. Reading older messages preserves scroll position; new arrivals follow only when
  the reader was near the bottom. Switching accounts and deleting a workspace clear chat cache.
- After a successful preferences save, the workspace selects and focuses Chat and shows a
  saved toast; a failed save keeps the user at the form. Preferences has its own navigation view.
- Workspace deletion now also deletes chat history through the membership foreign key cascade;
  the confirmation names messages explicitly. Existing payment audit records remain independent.
- Validation: 502 backend tests and 310 frontend tests pass, including 11 new chat integration
  cases, retry/pagination/XSS rendering tests and event/cache checks. Ruff, strict mypy, TypeScript,
  Biome WebAssembly checks and the production build pass; Alembic has one head at `0006_trip_messages`.
  Browser checks cover two sessions, persistence, live replies, lost-response retry deduplication
  and older history at 1366 x 768 and 1920 x 1080. Test-created chat workspaces are cleaned up.

## Delivered: basic desktop workspace UI/UX

The user asked to align the implemented interface with the saved desktop concepts before adding
more product features. The new shell uses the existing React/component system and a warm,
accessible coral palette. This is the basic workspace for manual review, not the complete concept
with researched maps, plan versions and payment features.

- Persistent left rail: Chat, Plan, Bookings, Trip overview, Splits, Preferences and Group;
  All trips, Account and demo-persona switching remain directly accessible.
- A compact header shows the real trip name, current members/avatars and account menu.
  No plan version or destination is fabricated; the status says No plan selected.
- Plan shows chat beside the empty itinerary/map area. Chat gives the conversation more room.
  Both panels fit the tested desktop height; the chat composer stays accessible while history
  scrolls independently. The empty plan offers real links to preferences and group setup.
- Preferences is a separate readable form with a privacy explanation. Group contains real
  membership, invite and deletion controls; they no longer dominate the planning workspace.
- Views are stored in the URL so reload/Back work. Hidden views preserve unsent chat and
  preference drafts; inactive controls stay out of keyboard navigation. Saving preferences
  switches to Chat. Unknown trip errors include a way back to the trip list.
- Bookings and Splits open honest coming-later views. There are no pretend plans, locations,
  balances, provider quotes or connected payment controls.
- Validation: 311 frontend tests, eight desktop browser tests, TypeScript, Biome and build pass. Browser coverage includes
  both 1366 x 768 and 1920 x 1080, side-by-side geometry, visible essential actions, keyboard
  navigation, draft preservation and all existing chat/preferences/group flows. Screenshot
  outputs are under ignored `web/test-results/`. Backend behavior is unchanged from the
  previously passing 502-test baseline.

Next: user review of the workspace, then private concerns and an explicit
planning request with a durable visible lifecycle. After that, add plan versions/items,
deterministic shares, the day view/map, bounded sourced Pilot research and replanning acceptance.
Do not present a queued request as a working intelligent planner before the worker exists.

Payment stage 0A remains unresolved. The member-to-personal-leader transfer must be proven or an
alternative explicitly agreed before stage 10. Existing authorization-hold experiments are not
the chosen contribution flow. Travel-data stage 0B and final model/provider selection remain
open; no paid integration or provider account was provisioned in this slice.
