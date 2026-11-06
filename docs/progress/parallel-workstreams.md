# Parallel work streams for teammates

Updated November 6, 2026. These are suggested ownership boundaries, not assignments to named
people. All work should build on the current workspace branch rather than rebuilding its
authentication, membership, event delivery or chat.

## Work that can start independently now

| Stream | Deliverable | Own these files/modules | Dependencies and acceptance |
| --- | --- | --- | --- |
| A · Group context and privacy | Trip editing/dates/timezone, followed by owner-only private concerns and their UI | New `trips/concerns.py` or a dedicated discussion module, focused trip-detail services, new frontend context components and privacy tests | Reuse existing membership checks. Validate dates/timezones. Another member must not receive private input through APIs, SSE, logs or summaries. Agree what Pilot may read before passing private concerns to a model |
| B · Plan domain and deterministic costs | Immutable `PlanVersion`/`PlanItem`, participants, sourced/estimated cost inputs, pure cent-based shares, draft itinerary/day view | New `planning/` domain, pure share calculator, new `web/src/features/planning/` components and tests | Can start with clearly labeled fixtures before live research exists. Stable item/member IDs; exact deterministic remainder allocation; totals reconcile; no invented availability or payment success |
| C · Travel research and provider adapters | One destination proof with source links, place IDs/coordinates, route evidence, price provenance/freshness; typed provider interfaces and failure/quota behavior | New provider/adapters modules, sanitized fixtures, focused evidence under planning/research docs | Independent of final UI. Research/verify provider access and terms before relying on a service. Do not silently provision paid services. Return typed facts/references rather than executable plan or payment commands |
| D · Platform and payment feasibility (optional fourth owner, or platform teammate) | Verify hosting/deployment state, secret rotation status, judge/demo prerequisites; resolve the exact personal-account transfer feasibility question | Existing ops scripts/config, operations evidence, payment-feasibility docs and isolated tests | Follow existing promotion rules. Preserve individual payment consent. Do not select merchant checkout, holds, payouts, custody or manual confirmation as an unapproved substitute |

With three people, A/B/C can proceed together; schedule D explicitly with the platform/payment
owner rather than assuming it is complete. A should finish one small reviewable context/privacy
slice before expanding it. B does not need to wait for the model or travel provider to define
and test plan correctness. C does not need a finished map UI to prove usable travel data.

## Integration work that follows the first contracts

| Work | Can start when | Completion check |
| --- | --- | --- |
| Explicit Pilot request + durable lifecycle | The authorised context boundary and plan-output schema are agreed | A button/request returns a real queued run ID; jobs survive restart; progress/errors are visible; one active run per trip; no fake completed planner |
| Bounded Pilot orchestration | B's plan schema and C's research interface are stable | Explicit invocation creates a sourced draft, with limits, usage records, structured validation and a recoverable provider/quota error |
| Initial selection and decisions | Plan revisions/participation and public chat contracts exist | Leader selects an initial version; old versions remain inspectable; responses bind to a specific immutable revision |
| Replanning and acceptance | Versioning, cost projections and selection are working | Cancellation preserves unrelated/completed history; affected-member acceptance, silence deadlines, discussion/opt-out and fresh recalculation follow the recorded rules |
| Booking coordination | Stable plan items/participation and private attachment access exist | Tasks distinguish who books/pays, provider handoff and independently evidenced confirmation |
| Connected money / settlement | Supported payment route is demonstrated and explicitly agreed; accounting contracts exist | Contributions are not double-counted as merchant expenses; obligations/arrangements require acceptance; provider events are reconciled; no payment without individual approval |

Do not have several people independently implement overlapping planner agents, payment flows or
alternative state models. The first complete target remains the recorded planning/replanning
slice, not simultaneous completion of every menu entry.

## Shared contracts and merge ownership

1. **One integration owner manages migrations.** A and B will both need schema changes. Agree
   revision IDs/order when merging; do not each introduce a competing `0007` head.
2. **Keep feature code separate.** Teammates create feature modules/components. The integration
   owner wires `app.py`, `TripPage.tsx`, `TripWorkspace.tsx`, route composition and import boundaries
   so these shared files do not become parallel editing hotspots.
3. **Agree a small interface before coding across streams.** Inputs: authorised trip/member IDs,
   public messages, consented context and timezone. Output: immutable plan items, participant IDs,
   source references and cost inputs. Money totals are computed by code, not model prose.
4. **Publish only safe events.** Commit domain records and event notes together. Public trip
   events must not carry private concerns/budgets/dietary fields. Each viewer refetches an
   authorised projection. New feature caches must be cleared on account changes.
5. **Use the generated client.** Run `scripts/dump_openapi.py` and `npm --prefix web run gen:api`
   after contract changes; generated schema/type files remain ignored. Do not hand-edit them.
6. **Review small branches.** Suggested names: `codex/group-context`, `codex/plan-domain`,
   `codex/travel-research`, `codex/platform-readiness`. Run focused tests, then the shared suite
   for the integrated slice. Use the two recorded desktop sizes; mobile work stays deferred.

Keep the desired payment flow and the individual-consent rules from `docs/planning/` intact.
Before returning a financial projection from a proposal, distinguish estimates, incurred costs,
additional cash required, expected refunds and confirmed refunds.
