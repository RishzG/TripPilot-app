# Milestone 01: one complete planning-and-replanning slice + payment feasibility

**November 6, 2026:** implementation is now authorized by the user's explicit request. The earlier
design-only restriction below is historical. Work has started with the group workspace's travel
preferences; see [implementation progress](implementation-progress-2026-11-06.md). This does not
claim the full milestone is delivered or resolve the payment decision gate.

Prepared November 3, 2026. Status: proposed implementation specification. No application implementation or sandbox transfer has been performed as part of writing this document.

Latest clarification: prior code is setup/sponsor experimentation only. No feature in this milestone is assumed implemented. The [from-zero feature map and architecture](feature-map-and-architecture.md) now governs build order and architecture; this document retains the detailed planning/replanning scenarios.

The user explicitly selected **technical design only for now** after this milestone was drafted. The delivery order below describes future implementation; it is not an instruction to start coding.

Demo platform: **desktop web app only**. Suggested verification viewports are 1366 x 768 (laptop) and 1920 x 1080 (desktop). These are proposed test sizes, not a restriction on the underlying API. Mobile layouts, phone-browser tests, PWA/native packaging, and touch-specific polish are deferred.

Read [the discussion archive](discussion-and-decisions.md) first for confirmed decisions and open questions. This milestone follows the user's friend-group model, not an agency portal or coordinated authorization holds.

## Outcome

One group can discuss a short trip, invoke Pilot, inspect a sourced day-wise plan and map, select an initial version, report a cancelled activity, compare an alternative and budget difference, and finalize a replacement through the agreed acceptance/deadline rules. Independently, produce an evidence-backed decision on verified PayPal contributions to the leader.

The planning slice must remain useful if payment integration is unresolved. It may generate booking/contribution tasks marked not yet connected; it must not show fictional successful transactions.

## Demonstration scenario

Suggested fixture, not a final destination decision: four US friends, USD, a three-day trip to one researched region, one shared stay, and a mix of free/paid activities. Use relative future dates when seeding. Each person has an origin, preferences, and a per-person budget. All sample prices remain labeled until tied to a real source or supplied quote.

1. Leader creates the group and members join through the identity/invite flow built for this product.
2. Chat includes preferences and one conflicting suggestion; the leader invokes `/plan` or the equivalent button.
3. Pilot publishes its understanding, asks one unresolved question if needed, researches a bounded set of options, then proposes version 1.
4. Members can inspect sources, an itinerary, a day map, and estimated shares. The leader selects version 1.
5. During the trip a member reports the scheduled outdoor activity is cancelled.
6. Pilot produces replacement proposal 2 based on version 1, preserving unrelated and completed items.
7. The proposal shows changed times, route, participants, booking implications, and per-person budget differences, including uncertain refunds.
8. Required participants accept. In a second run, one member is silent and the leader finalizes only after the announced deadline. Record which path was used.
9. Version 2 becomes active, history remains visible, and relevant booking tasks update. No payment is authorized merely by accepting the itinerary.

## Boundaries of this slice

Include chat, basic preferences, one reusable question/poll type, a real bounded research call, structured itinerary proposals, source attribution, map/day selection, immutable versions, affected-person acceptance, deadline handling, and budget diffs.

Defer receipt OCR, complete trip settlement, agency portals, autonomous merchant checkout, deep-cart generation across arbitrary sites, a full catalog of interaction formats, and AG Studio analytics. Research and UI adapters should allow those later without requiring them now.

## From-zero foundation

Build and verify the application shell, identity, membership, database/migrations, job execution, event delivery and accounting foundations as part of this product. Earlier setup/sponsor experiments do not count as completed features or dictate framework choices. See the current architecture document for independent technology recommendations.

## Proposed architecture and interfaces

### Commands and live updates

- HTTP handles posting messages, invoking Pilot, responding to decisions, selecting plans, and finalizing changes.
- Implement trip SSE for persisted `message.created`, `pilot.run.updated`, `proposal.created`, `decision.updated`, `plan.selected`, and `booking_task.updated` events.
- Enforce membership on every command and event subscription. Reconnecting clients replay from the last event ID, then refetch the current plan when replay is unavailable.
- Persist state before publishing live events. Use a transactionally written outbox for reliable job dispatch if enqueueing cannot share the business transaction.

Proposed route groups (align exact prefixes with the new API contract):

| Route | Behavior |
| --- | --- |
| `POST /trips/{id}/messages` | Save an ordinary message or an explicit Pilot invocation |
| `GET /trips/{id}/messages` | Cursor-paginated authorized history |
| `POST /trips/{id}/pilot-runs` | Queue planning/replanning against an explicit base version; return `202` and run ID |
| `GET /trips/{id}/pilot-runs/{runId}` | Progress, result, or actionable error |
| `GET /trips/{id}/plans` | Immutable version history and active selection |
| `POST /trips/{id}/plans/{versionId}/select` | Leader selects an initial version; authenticated, version-checked command |
| `POST /trips/{id}/proposals/{proposalId}/responses` | Required member accepts, requests leader discussion, or explicitly opts out of proposed participation |
| `POST /trips/{id}/proposals/{proposalId}/finalize` | Check proposal/base version, acceptance/deadline, and caller permissions atomically |
| `GET /trips/{id}/budget` | Deterministic estimate/spending/contribution summary; filter private fields |

Commands that can be retried carry an idempotency key. Mutations affecting plan state include an expected/base version; stale operations return a conflict and the current version identifier.

### Proposed types

- `TripPreferences`: dates/day count, timezone, trip styles, approximate budget, origins and travel preferences. Keep member-private input out of public projections.
- `Message`: trip, author, content, timestamp; separate public messages from private submissions.
- `PilotRun`: initiator, purpose, base version, state, limits, usage, source references, result/error.
- `ResearchReference`: provider, URL/place ID, retrieved-at timestamp, relevant facts, price provenance; storage follows provider terms.
- `PlanVersion`: immutable snapshot, parent version, initiating request, change summary, creator, computed totals, created-at timestamp.
- `PlanItem`: stable identity, type, place/source reference, timezone-aware schedule, participant set, price input and confidence/status. Persistent booking links remain outside replaceable snapshots.
- `ChangeProposal`: immutable revision, base version, changed items, required approvers, responses, announced deadline, status, finalization reason.
- `BookingTask`: item, owner/payer, participants, source link, estimated price, contribution status, booking status, confirmation reference.
- `CostArrangement`: leader-proposed allocation adjustment linked to an existing expense/booking and opt-out; records before/after shares, affected members, immutable revision, responses, and application status.

Store schema-validated structured fields rather than extracting business state from the model's conversational prose. Use relational records for authorizations, responses, and money; a validated immutable JSON snapshot can hold itinerary presentation details.

## Pilot execution

```mermaid
sequenceDiagram
    participant U as Member / leader
    participant A as FastAPI
    participant D as PostgreSQL
    participant W as Worker / Pilot
    participant R as Model + research providers
    U->>A: Request plan/change with base version
    A->>D: Save request + durable dispatch record
    A-->>U: Run ID and queued status
    W->>D: Claim job; read authorized current context
    W->>R: Bounded research + structured planning
    R-->>W: Sources + structured proposal
    W->>W: Validate facts/shape; calculate shares in code
    W->>D: Save proposal and committed events
    D-->>U: Live proposal update
    U->>A: Responses / finalize request
    A->>D: Lock and validate base version + consent/deadline
    A->>D: Save new active version and event atomically
    D-->>U: Updated itinerary, map and budget
```

Use one orchestrator with a replaceable model adapter. Start by evaluating a low-cost Gemini option against representative group prompts rather than defaulting to a high-cost planner or multi-agent system. Explicit tools cover context read, search, place/route lookup, proposal drafting, and decision suggestion. No model-accessible payment execution tool.

Suggested initial operational ceilings, to tune from measured runs: one active planning run per trip, at most four model calls and six basic search calls per run, a 90-second run deadline, and at most one structured-output repair attempt. Late results remain draft proposals and never overwrite a newer active plan. Do not spend twice on an already completed/replayed request.

Use a small curated fixture for deterministic integration tests, but demonstrate at least one live research run. Cached/fixture data is visibly labeled and is not described as a live quote. Per-user/session and aggregate limits use a central counter; stop paid work before exceeding the configured allowance. Provider-specific storage restrictions and rate limits apply.

## Replanning and approval rules

- Determine affected people from changed participation, schedule dependencies, shared transport, and cost. Present the required approver set before collecting responses.
- Acceptance binds to a specific immutable proposal revision and computed cost summary.
- A material change creates a new proposal revision; do not carry forward acceptance silently.
- If all required people accept, the application finalizes the proposal atomically; the leader does not need an extra action for the unanimous path.
- If a required member is silent, the leader may explicitly finalize only after the announced deadline. Silence before that point is not consent.
- On explicit rejection, offer discussion with the leader or opt-out. Discussion remains unresolved until the member accepts, opts out, or the proposal is revised/withdrawn; it is not silence or consent. The user has not authorized a leader override of an explicit rejection.
- An explicit opt-out changes proposed participation, not trip membership. Recalculate schedules, shares, and the affected-person set, publish a new immutable proposal revision, and collect fresh acceptance from everyone affected. Do not silently carry responses from the prior revision forward.
- Opt-out does not automatically cancel an external booking, confirm a refund, or erase an already incurred obligation. For non-refundable costs, the leader proposes a case-by-case arrangement for affected members to accept. Keep the current allocation until agreement is complete.
- Cost arrangements are separate from itinerary proposals. Record old and proposed shares, explain who covers any released share, and require acceptance from every member whose obligation or reimbursement changes. Share adjustments preserve the recorded expense total unless a separate verified refund/correction changes that total.
- A response deadline never makes silence consent to a changed financial obligation. The leader's itinerary override does not apply to cost arrangements. Apply an accepted arrangement atomically once, with an audit entry and no automatic transfer; actual payments still need individual approval.
- Individual payment approval is required regardless of discussion, opt-out, itinerary acceptance, or leader finalization.
- If membership or the active base version changes, re-evaluate participants and costs; invalidate stale finalization.
- No itinerary acceptance or leader override authorizes another person's payment.
- Completed activities, paid bookings, non-refundable costs, and confirmed refunds retain their history when an itinerary changes.
- A cancellation reported in chat is a reported condition, not proof that the merchant cancelled or refunded a booking.

## Budget and accounting for this slice

Calculate equal shares in cents with stable deterministic remainder allocation. Track participants per item. Monetary display text must use backend-computed values.

Show separately:

1. Estimated cost of the selected plan.
2. Confirmed money already spent.
3. Additional amount needed for the replacement.
4. Refunds confirmed versus expected/not requested.
5. Each affected person's change in expected total.

Example: a USD 45 cancelled activity replaced with a USD 30 activity adds USD 30 now if the original is non-refundable. If the original USD 45 refund is confirmed, the final net saving is USD 15. Do not show that saving as confirmed while refund recovery remains uncertain.

Contributions are transfers toward costs, not another merchant expense. Preserve this distinction even before the payment connection is built.

## Payment feasibility proof

### Exact question

Can a supported PayPal integration, in US/USD sandbox, let one ordinary member explicitly send a share to the group leader's intended personal account and let TripPilot independently verify the recipient, amount, currency, and final status without collecting user passwords or pretending the leader is TripPilot's merchant account?

### Current evidence

See [the dated evidence log](payment-feasibility.md) for official links, the initial verdict, and the support question draft. No sandbox test was executed: this checkout currently has no PayPal application credentials, and intended personal-account verification permissions are unresolved.

| Area | Known evidence | Not yet established |
| --- | --- | --- |
| Identity | Log in with PayPal exposes consented identity claims | Login does not establish transfer/history authority |
| Payment links | PayPal.Me supports requesting contributions | Supported sandbox behavior and automatic callback/verification for this scenario |
| Transaction Search | Third-party history access requires partner access per published spec | Team eligibility and available permissions for intended leader account |
| Existing holds | Teammate code/test reports authorize/capture/void behavior | It is not personal-account P2P evidence |
| Existing payouts | Prior report says sandbox business-to-person payout works | It is not evidence of member-personal-account funding |
| Live proof | None performed in this milestone | Intended end-to-end transfer and verification |

### Investigation sequence

1. Inspect current official API/sandbox documentation and, if needed, ask the PayPal hackathon support team through the user's chosen channel. Do not send any messages externally without authorization.
2. Identify supported account types, consent, app/partner permissions, sandbox endpoints, and a server-verifiable transfer reference. Record exact evidence URLs and checked date.
3. Use a separate sandbox fixture with one sender and one leader recipient. Keep credentials in local environment/secret storage, never in docs, screenshots, or committed code.
4. Prove the smallest transfer with explicit sender approval. Read the resulting resource server-side or verify it through the supported mechanism.
5. Check wrong recipient, wrong amount/currency, abandoned approval, duplicate delivery, repeat submission, delayed success, refund/reversal, and temporary API failure.
6. Publish a short verdict: supported and demonstrated; access-gated/unavailable to this team; or still unproven. Capture safe request/transaction IDs and sanitized status evidence, not credentials.

Documentation research alone is not labeled an executed sandbox test. Personal payment links do not receive a fabricated completion callback. Browser automation using stored user passwords is not a substitute for a supported integration.

### Decision gate

If the intended transfer cannot be demonstrated, pause payment implementation and discuss alternatives. The user has not approved payment links plus manual confirmation, business-account checkout simulation, platform custody, or a return to capped authorization holds. Planning/replanning can continue independently.

## Verification and acceptance

### Planning

- A real chat leads to a sourced, structured proposal and a day-wise map.
- Missing details trigger a useful question instead of invented facts.
- Prices display provenance and freshness; unknown availability is explicit.
- The leader can select an initial version and inspect earlier versions.

### Replanning

- An affected-day cancellation yields alternatives, preserved unrelated items, and correct cost differences.
- Only the required participants can respond for themselves.
- Unanimous acceptance finalizes once, atomically.
- A silent member prevents early finalization; after the announced deadline the leader can finalize with an audit reason.
- Simultaneous finalization, stale proposals, modified costs, membership changes, and explicit rejection are handled visibly.
- A member can request discussion without being counted as accepted, silent, or opted out. Explicit opt-out produces a new proposal with recalculated schedules/costs and fresh acceptance; previous payment or booking history remains intact.
- An opt-out from a non-refundable booking lets the leader propose an allocation arrangement. Existing balances remain unchanged while acceptance is incomplete. Revisions invalidate old responses; duplicate application has no effect; an accepted arrangement preserves the expense total and does not execute a transfer.
- Accepting a plan never starts an unauthorized payment or claims an external booking is cancelled.

### Reliability, privacy, money

- A worker restart or repeated command does not create duplicate finalized plans.
- SSE reconnect restores current state; private concerns never appear in another member's API/event data.
- Cents add up for uneven splits, opt-outs, and replacement costs. Contributions are not double-counted.
- Prompt-injection text in a listing, message, or receipt cannot select plans, change permissions, or move money.
- Search/model quota failure produces a visible recoverable state and labeled cached fallback.
- Desktop browser tests cover the complete journey at laptop and larger desktop widths, including keyboard operation, scrolling, dialogs, and map/chat panel resizing without clipped essential actions. Phone-sized acceptance is outside the demo scope.
- Payment proof outcomes have corresponding sandbox evidence, or are honestly marked not executed.

## Suggested delivery order

1. Confirm implementation checkout and payment evidence needs; preserve existing work.
2. Define shared API/type contracts and migrations for messages, runs, versions, proposals, responses, and sources.
3. Build chat + fixture-backed itinerary/map + version selection.
4. Connect one bounded live Pilot research run with structured output and deterministic costs.
5. Add replacement proposal, cost diff, acceptance, deadline, conflict handling, and history.
6. Complete independent PayPal proof and discuss its result before choosing the payment design.
7. Run end-to-end acceptance and measure provider usage. Add sponsor polish only after the slice passes.

No fixed delivery-date promise is made until team capacity and current branch progress are confirmed.
