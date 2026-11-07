# Implementation status

Updated November 6, 2026. Roadmap stages refer to
[the feature map](../planning/feature-map-and-architecture.md). This report reflects source and
local verification, not a claim that the hosted demo is running the branch.

## Working functionality

| Area | What is implemented | Evidence / source |
| --- | --- | --- |
| Application foundation | FastAPI API, React/Vite frontend, PostgreSQL migrations, durable Procrastinate jobs, structured logs, health endpoint, generated API types | `src/trippilot/app.py`, `db/`, `jobs/`, `.github/workflows/` |
| Identity | PayPal identity integration, hashed sessions, demo personas, nickname/avatar editing for normal accounts, origin checks on writes | `auth/`, `demo/`; existing integration tests |
| Trips and membership | Create/list/open trips, organiser/member roles, invite preview/join, reset links, close/reopen joining, leave, remove and re-add, membership cap and demo fencing | `trips/router.py`, `service.py`, `invites.py` |
| Travel preferences | Per-trip origin, interests, pace, optional USD budget in cents and dietary notes; save/reload/clear; exact decimal-to-cent input handling | `trips/preferences.py`, migration `0005_travel_profiles`, `TravelPreferencesPanel.tsx` |
| Preference privacy | Only the owner receives budget/dietary fields; group projection allowlists origin/interests/pace; events contain no private values | Preference integration tests and desktop privacy checks |
| Group chat | Persisted plain-text messages, captured author name and aware timestamp, 4,000-character limit, cursor-paginated history | `trips/chat.py`, migration `0006_trip_messages` |
| Private concerns | Active members submit plain-text concerns (1-1,000 characters, 20 open each, retry-safe client UUID). The author sees and can withdraw their own; the leader sees other members' concerns as text and UTC date only, with no author identity or id (the leader's own appear only in their own list); other members see nothing. Lists are newest first and shown in a collapsible tile beside Chat. Withdrawing erases the text. `concerns.changed` events carry `{}` | `trips/concerns.py`, migration `0007_private_concerns`, `PrivateConcerns.tsx`, `test_private_concerns.py` |
| Shared scheduling context | Leader edits name/destination/dates/IANA timezone with revision conflicts | `planning/router.py`, `planning/domain.py` |
| Immutable plans and estimates | Stable items/participants/sources, version history, exact per-person cent allocation and stale-input detection | `planning/store.py`, migration `0008_planning` |
| Day itinerary and map | Date selection, sourced locations, OpenStreetMap viewer, whole-group and per-person USD estimates; clearly labeled Chicago fixtures | `PlanWorkspace.tsx`, `planning/sample.py` |
| Pilot lifecycle | Explicit Plan button; durable queued/running/failed/completed outbox, fenced restart recovery, bounded research and validated drafts. Live provider needs configuration and acceptance verification | `planning/pilot.py`, `planning/tasks.py` |
| Private plan fit | Per-member model calls consider private concerns, budget ceilings and dietary notes; deterministic budget enforcement and owner-only explanations. No private data in public research or events | `planning/pilot.py`, `planning/store.py` |
| Selection and cancellation | Initial leader selection; alternatives create immutable revisions with exact cost differences; all affected members must explicitly accept; stale inputs or rejection/discussion block finalization | `planning/router.py`, `test_planning.py` |
| Safe chat retries | Client UUID scoped to sender/trip, one row/event for concurrent retries, 409 for reusing an ID with different text; failed drafts retained | Chat API/UI tests; browser test discards a committed POST response and retries |
| Live updates | Database event log, NOTIFY/LISTEN bridge and member-authorized SSE; refetch on reconnect/tab return; message events refresh chat | `realtime/`, `useTripEvents.ts` |
| Workspace deletion | Organiser action remains visible; enabled only with no other active members. Left/removed members do not block it. Confirmation, race checks and JSON response | `delete_empty_trip`, deletion integration tests, desktop tests |
| Desktop UX | Persistent navigation, trip/member header, dedicated full-width Chat, separate Plan workspace, Preferences, Group and read-only Trip overview | `TripWorkspace.tsx`, `TripPage.tsx` |
| Chat usability | Most panel height goes to history; compact auto-growing composer; inline Send; Enter adds a line, Ctrl/Command+Enter sends; drafts survive view changes | `GroupChat.tsx`, UI and desktop layout tests |

The latest UX intentionally separates Chat and Plan. It does not just vary the width of the same
two panels. Group management belongs in Group; the header and Trip overview show member context
without a management button. Bookings and Splits are clearly marked coming later.

## Existing payment infrastructure

The repository already has a typed PayPal gateway/fake, token caching, encrypted saved-payment
tokens, authorization/capture/void/reauthorize operations, simulated-buyer pool administration,
verified webhook storage and an append-only payment audit ledger. Existing sandbox spikes are
evidence of those specific operations, not proof of the desired personal-account transfer flow.

The webhook worker records events; complete provider-resource reconciliation is not implemented.
The typed client still lacks the later payouts/refunds/pay-now work described in the foundation
assessment. No new money movement or payment fallback was introduced in this branch's workspace
features. See [payment feasibility](../planning/payment-feasibility.md).

## Roadmap coverage and gaps

| Stage | Status | Remaining work |
| --- | --- | --- |
| 0A · Payment feasibility | Unresolved | Demonstrate the intended member-to-leader transfer and independent verification, or discuss an alternative before implementation |
| 0B · Travel data | Partial research/spikes | Live acceptance of bounded, sourced AI research; dedicated place/route adapters and independent location/price verification remain |
| 1 · Foundation | Existing foundation locally verified | Operational readiness and deployment evidence still need separate verification |
| 2 · Group workspace | Partial | Trip editing/dates/timezone, membership and personal preferences work; broader preference controls remain |
| 3 · Conversation | Partial | Public chat, private concerns and durable button invocation are implemented in this workspace; `/plan` remains ordinary chat text |
| 4 · Plan model / budget / map | Implemented for USD estimates | Versioned day itinerary, sourced items, participant shares and map work; actual accounting and provider availability remain separate |
| 5–7 · Pilot / decisions / replanning | Core flow implemented; live acceptance pending | Bounded sourced drafts, private fit checks, leader selection, revision cost differences and affected acceptance work in local tests. Credentials/provider verification, advanced clarification, deadlines and opt-out policies remain |
| 8–9 · Transport / bookings | Not implemented | Arrival arrangements, booking tasks, provider handoffs and private confirmation storage |
| 10–11 · Contributions / accounting | Not implemented | Agreed payment route, verification/reconciliation, expenses, covers, accepted cost arrangements and settlement |
| 12 · Demo completion | Partial | Basic shell, personas and error states exist; real dashboard projections, reset flow, quotas, judge access and end-to-end product demonstration remain |

`/plan` sent as a chat message is ordinary text today. There is no hidden planner behind the
composer, no automatic booking, and no payment authorized by discussing or saving a preference.

## Data and deployment notes

- The migration chain has one head: `0008_planning`, following `0007_private_concerns`.
- Deleting an eligible workspace cascades its membership-owned preferences/messages and invites.
  Existing append-only payment audit records are independent. Before introducing bookings or
  accounting, define their retention behavior explicitly rather than blindly extending cascades.
- Local preview validation uses fake payments and an isolated development database. Test fixtures
  derive a separate database whose name ends in `_test`.
- CI and Render promotion infrastructure predate this slice. Hosted production was last observed
  suspended earlier on November 6; it was not resumed or deployed as part of this work.

See [planning workspace details](planning-workspace.md) for the current privacy boundary, model limits, configuration and sample restrictions.
