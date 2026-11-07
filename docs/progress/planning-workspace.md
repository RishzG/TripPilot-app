# Shared planning workspace

The Plan workspace now owns shared trip details, immutable itinerary versions, day views,
an OpenStreetMap place viewer, deterministic USD estimates, explicit Pilot requests and
version-bound cancellation proposals. These changes extend the private concerns feature
merged in PR #24.

## Shared context and estimates

Only the leader edits the trip name, destination, date range and IANA timezone. Dates must
be supplied together and span at most 31 days. A context revision rejects concurrent edits.
Pilot rejects overlapping participant schedules, invalid local DST times and missing days.
Each item records a stable ID, location/coordinates, participants, sources, evidence and an
estimated whole-group cost in integer USD cents. Shares divide cents equally, assigning any
remainder in sorted account-ID order. Totals are computed by code on every read.

Versions are append-only through the API and protected against SQL updates. Changes create
new versions. Fingerprints cover scheduling context, active membership, public preferences,
private budgets/dietary notes and open concerns. Changing these inputs prevents stale
versions or proposals from being selected or finalized; history remains inspectable.

## Privacy and fitting the whole group

The intended outcome is one plan that satisfies everyone's hard constraints while balancing
softer preferences. A saved budget is a hard ceiling for the itinerary estimates shown; it
does not imply that unlisted flights or lodging are covered. Unresolved dietary safety or
other hard constraints must block a draft rather than be represented as resolved.

Pilot sends shared context and public preferences to its research call. Private fields are
excluded from research queries. Each subsequent private model call receives one member's
own budget, dietary notes and concerns, plus the public candidate activities. It can only
select existing public candidate IDs and write that member's private explanation. It cannot
rewrite public titles or descriptions using private information. The intersection is checked
again if filtering changed the itinerary, and budgets are enforced deterministically.

Private explanations are stored separately and returned only to their owner after a current
membership check. Leaders do not receive other members' explanations. Concerns retain their
existing anonymous leader projection. Events contain only `{}`. Provider errors and validation
errors are replaced with safe messages; raw prompts and private model output are not logged.
The configured model provider processes private notes during fit evaluation. Members are
informed of Pilot's use in the concerns and preference UI. Model assessment is advisory and
does not establish medical safety or member agreement; confirmations still matter.

## Durable Pilot execution

Configure `AI_GATEWAY_API_KEY` and `PILOT_MODEL` in both the API and worker environments.
The model must support the [AI Gateway Responses API](https://vercel.com/docs/ai-gateway/sdks-and-apis/responses)
and web search. No SDK dependency or paid resource is provisioned by this implementation.
Without configuration the UI explicitly disables live invocation and the API returns 503.

The leader's Plan button writes a durable `queued` row in PostgreSQL. A retry UUID deduplicates
ambiguous requests, and a partial unique index permits one active run per trip. The existing
Procrastinate worker imports `trippilot.planning.tasks` and polls this transactional outbox
every minute. States are queued/running/failed/completed. Six-minute fenced leases allow
recovery after process loss; two attempts maximum prevent endless retries. An execution has
a 210-second deadline, at most three public web-search calls, one research request and up to
two private evaluation passes (at most 25 model requests for a full 12-person group). Private
calls have concurrency three; each HTTP call has a 90-second timeout and 12,000 output-token
cap. Provider quota errors become recoverable failed runs. Only sources present in provider
search evidence can enter live drafts. A draft is saved atomically with private notes and
completion state, after rechecking input freshness.

Research and model availability, coordinates, prices and estimates still require human
verification. The map displays places, not verified routes or journey times. `/plan` in public
chat remains ordinary text; invocation uses the explicit Plan button.

## Selection and cancellation

The leader selects an initial current draft. Later changes go through a proposal tied to the
selected base and exact immutable revision. Cancelling an item presents saved alternatives;
Research alternatives requests new sourced candidates for the same day. Proposing an option
replaces exactly one item and preserves unrelated IDs, source references and costs. Live
proposals check the full resulting itinerary against private constraints again. Their public
projection contains exact per-person estimate differences and affected-member responses.

Every affected member must explicitly accept that revision before the leader applies it.
Rejection, discussion, missing responses, changed inputs or a changed selected base prevent
finalization. Silence is not treated as consent. A different alternative creates a different
proposal with fresh responses. No booking, charge, refund or money transfer occurs.

## Sample and verification

Load Chicago sample creates two clearly labeled illustrative versions with official visitor
links, fixed demonstration estimates and known place coordinates. No private fit assessment
is claimed for samples. Real trips can inspect samples; only demo trips can select them.
Samples and live drafts cannot be mixed in a proposal.

Migration `0008_planning` follows `0007_private_concerns`. Focused tests cover exact-cent shares,
dates/timezones, DST gaps, ownership, immutable history, private input separation, constraint
conflicts, stale selection, provider quotas, durable run processing and affected acceptance.
`web/e2e/planning.spec.ts` exercises the shared sample selection and two-member cancellation
acceptance flow at both recorded desktop sizes. Set `PLAYWRIGHT_BASE_URL` to target an isolated
local server instead of the default Compose URL.

The full suite deliberately exceeds the application's 10 invite requests/minute/address
limit. For a combined run, `scripts.smoke.browser_app:create_browser_app` supplies a local-only
factory that overrides just that dependency. It refuses production/shared database names and
requires a loopback public URL plus a disposable `*_preview` or `*_test` database. Backend
integration tests retain and verify the real quota. This fixture is not a deployment entrypoint.

Live external-model execution needs credentials and has not been represented as verified by
sample or mocked-provider tests. Deployment and migration of a shared environment are separate
from these local changes.

Final local results: 538 backend tests, 342 frontend tests and 12 desktop browser cases passed; strict mypy, Ruff, TypeScript, Biome lint and the production frontend build passed. Changed frontend files pass formatting; untouched Windows CRLF files prevent a clean full-tree formatter check.


## Morning preparation (November 7)

Migration `0009_requirement_priorities` adds private Must have and Prefer text fields. Both
participate in input fingerprints and are sent only to the owner's fit assessment. Budget
ceilings and dietary safety retain their existing required status. A member can propose their
own activity opt-out; the estimated activity total stays fixed and remaining participant
shares are recalculated. Last-participant opt-outs are blocked. A request for another
alternative blocks application just like discussion or rejection. Each new proposal needs
fresh responses from all affected members.

Day and map controls expose their selected state. The budget includes the current day's total,
and inspecting another version shows its group delta and changed/removed activity counts.
See [morning walkthrough](../planning/morning-group-walkthrough.md) and
[proposed AI evaluation cases](../planning/ai-evaluation-cases.md). Group review and live
provider evaluation remain pending.


Validation for the November 7 additions: 25 focused UI tests and six synchronous domain tests
passed; TypeScript, production build, strict mypy on changed backend modules, Ruff, and Biome
on the edited screens passed. Added integration cases cover private requirement persistence
and stale fingerprints, fixed-cost member opt-outs, and fresh acceptance. Their execution
remains unverified in this session: sandbox loopback access was denied, the escalated database
connection timed out, and async unit tests stalled in Windows socketpair creation. The older
full-suite results above predate these additions. No shared deployment or migration was run.
