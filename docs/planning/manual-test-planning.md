# Manual acceptance: planning workspace

Status: **not yet performed by the team**. Check items only after observing the expected result.
Record date, app version/commit, environment, tester/persona, browser size, actual result and
issue link. Mark blocked checks explicitly rather than counting them as passes.

## Setup and evidence

- [ ] Use disposable demo trips and separate browser profiles/private windows for Maya (leader),
  Sam and optionally Ana. Normal tabs share the sign-in cookie. Join through Maya's Group invite.
- [ ] Confirm the app database is migrated through `0008_planning`. For the latest Must have /
  Prefer and opt-out walkthrough, also apply `0009_requirement_priorities` before using the app.
- [ ] For live checks, configure `AI_GATEWAY_API_KEY` and `PILOT_MODEL` in both API and worker,
  and run the Procrastinate worker. Use synthetic preferences and private concerns.
- [ ] Record which environment and commit supplied the earlier results: **538 backend tests,
  342 frontend tests, 12 desktop browser tests, type checks and build**. These are automated
  evidence for the earlier planning slice, not completed manual checks or verification of
  the later priority/opt-out additions. See the latest validation note in
  [planning workspace](../progress/planning-workspace.md).

## Trip dates, timezone and editing

- [ ] As Maya, save trip name, Chicago, matching start/end dates and `America/Chicago`. Reopen
  and refresh: values persist. Sam sees the same details and has no editing controls.
- [ ] Edit the name/destination/dates/timezone again. The new values appear for other members;
  saved details collapse and can be reopened. Itinerary times are labeled with the timezone.
- [ ] Try an invalid timezone, only one date, an end before the start, and a range over 31 days.
  Each save is rejected with useful feedback; previously saved details remain intact.
- [ ] With two leader sessions, attempt conflicting saves from the same revision. A stale save
  must not silently overwrite the newer context. Reload and review the current values.
- [ ] Change dates or timezone after creating a plan/proposal. Older versions remain in history
  but are marked stale and cannot be selected or applied as current decisions.

## Immutable versions, shares, itinerary and map

- [ ] Save all member preferences before loading samples. Load Chicago sample once, choose
  Chicago sample day, and select it for the demo. The sample/estimate warning stays visible.
- [ ] With two members, Art Institute is $64 group / $32 each; with three, $96 / $32 each.
  Millennium Park is $0. Item shares sum to each item's total; member totals sum to the group
  total. No estimate is presented as a charge, booking, refund or live price quote.
- [ ] Select each place button: its selected state and single map marker change to the chosen
  location. Numbering matches the itinerary order. Official source links open the expected
  visitor pages. The map does not claim verified routes or travel times.
- [ ] Review at laptop and wide desktop sizes, then use Tab/Enter. Day controls, map buttons,
  source links and version controls remain readable, reachable and visibly focused.
- [ ] Use a successful multi-day live draft for day navigation: switch between days and versions.
  Activities appear in local-time order on the correct day; active state and daily total update.
  The whole-itinerary total remains distinct. The one-day sample cannot verify multiple days.
- [ ] After applying a replacement, reopen the original version. Its titles, sources, participants,
  costs and times are unchanged. Inspect the revision: unrelated activities retain their IDs
  and data; group cost difference and changed/removed counts match the actual changes.
- [ ] If a live draft offers a total with remainder cents, verify stable exact allocation, e.g.
  $10.01 across three members is $3.34/$3.34/$3.33 in account-ID order. If no such draft is
  available, mark this manual check blocked and retain the deterministic automated evidence.

## Durable Pilot jobs, private fit and explanations — live configuration required

- [ ] With no provider configuration, live invocation is disabled with setup guidance; the
  sample remains usable. Typing `/plan` in Chat sends ordinary text.
- [ ] Save different synthetic budgets, dietary notes, Must have / Prefer fields and private
  concerns as each member. Reopen each form: saved values persist and other members cannot
  read the owner's private fields. Existing anonymous leader concern visibility still applies.
- [ ] As Maya, invoke Plan with Pilot once. Observe queued/running then completed, or a safe
  recoverable failure. Navigation and refresh retain the request; a completed request creates
  a sourced draft. Sam has no leader invocation controls.
- [ ] During an active request, try starting another. It must not produce parallel duplicate
  work. Navigate away and return: the same durable request remains visible.
- [ ] In a disposable local environment, stop the worker, queue a request, then restart the
  worker. The queued request is picked up. Separately interrupt a running worker and restart
  it: after the documented six-minute lease/retry window, it recovers or fails safely without
  duplicate completed drafts. Never perform this check on a shared worker used by others.
- [ ] Trigger a controlled provider failure in the disposable environment (such as invalid
  test credentials). A safe error appears without raw prompts, private values or provider
  output. Restore valid configuration and confirm a new request can succeed.
- [ ] Review personal explanations as Maya and Sam. Each receives only their own private
  explanation; public itinerary/research and other members' explanations reveal no private
  budget, notes, requirements or identity behind anonymous concerns.
- [ ] Withdraw a private concern after generation. The owner's potentially derivative stored
  explanations disappear. Changed inputs stale existing plans/proposals.
- [ ] Run the proposed [AI evaluation cases](ai-evaluation-cases.md): conflicting budgets,
  allergies, accessibility, soft tradeoffs and no feasible shared plan. Record expected versus
  actual outcomes. Insufficient evidence must not become a claim of safety or accessibility.
  Inspect source support, coordinates and estimate uncertainty independently.

## Cancellation alternatives and fresh acceptance

- [ ] On a selected Chicago sample, Maya chooses Cancel / find alternatives for Art Institute.
  Cultural Center appears with a $0 estimate and a -$64 group difference for two members
  (-$96 for three). Proposing it leaves the selected itinerary unchanged.
- [ ] Review the proposal's revision and differences: each original participant saves $32.
  The original version remains unchanged; each affected member starts Awaiting response.
- [ ] Maya accepts; Apply stays disabled until every affected member accepts the exact revision.
  Test Needs discussion, Reject, and Request another alternative separately. Each blocks Apply;
  silence also blocks it. Discuss in Chat and keep private inputs private.
- [ ] Propose another alternative/revision after disagreement. Its responses start empty;
  acceptance of a different proposal is not carried forward. All affected members accept,
  then Maya applies. Sam cannot apply it; the selected plan changes only after finalization.
- [ ] In separate disposable runs, change preferences, membership, dates or the selected base
  while a proposal is open. Old proposals become stale and cannot be finalized.
- [ ] With live configuration, Research alternatives creates sourced same-day candidates for
  the selected activity. A proposed live replacement checks the resulting itinerary against
  private constraints again. An infeasible alternative fails without changing selection.

## Later additions: priorities and opt-outs

- [ ] Must have requirements block an incompatible live draft; Prefer can be traded off with
  a private explanation. Budget ceilings and dietary safety remain required constraints.
- [ ] Use a fresh selected paid sample before replacing Art Institute with the free option.
  Sam chooses Propose my opt-out. In a two-member trip the $64 total stays fixed: Sam's activity
  share becomes $0 and Maya's becomes $64. Differences are -$32 and +$32; they sum to zero.
- [ ] The opt-out remains a proposal until Sam and Maya both accept and Maya applies it.
  Any previous responses do not carry forward. Other activities and the old version persist.
- [ ] The final participant cannot opt out through this flow. A member cannot opt out another
  person. Changed private inputs or membership invalidate the opt-out proposal as usual.

## Results

| Check / persona | Expected | Actual | Pass / fail / blocked | Issue / evidence |
| --- | --- | --- | --- | --- |
| | | | | |

The group walkthrough, external-provider run and provider comparison remain pending until
performed and recorded. Automated pass counts do not fill these result cells.
