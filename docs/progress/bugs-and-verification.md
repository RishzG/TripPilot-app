# Bugs, UX feedback and verification

Updated November 6, 2026. Resolved items below came from the user's testing or implementation
verification. An unfinished feature is listed separately from a confirmed defect.

## Resolved reports

| ID | Report | Resolution | Verification |
| --- | --- | --- | --- |
| UX-01 | Example text looked like entered defaults, making saves appear ineffective | Hints start with `Ex.` and use lighter italic text; untouched fields remain empty | Placeholder/browser check; user identified the original confusion |
| UX-02 | Group summary appeared unchanged after Save | Save returns the complete caller-filtered projection; client cancels stale reads and updates the cache directly; account switching clears preference cache | API response test and UI regression without a follow-up GET. The original confusion also involved UX-01; a data-loss bug was not established |
| UX-03 | Negative budget produced the generic decimal-format message | Explicit `Budget cannot be negative.` error; decimal precision and upper-limit errors remain separate | UI and desktop checks; backend rejects invalid cents |
| UX-04 | Delete did not appear; the original rule disallowed previously shared trips | Delete stays visible to organisers, disabled while other active members remain; all left/removed permits deletion | Active/left/removed and re-add tests; simultaneous join/delete test; browser flow |
| UX-05 | Saving preferences did not lead to chat | Successful save selects/focuses Chat and displays a saved toast; failures retain the form | UI callback test and browser focus/navigation check |
| UX-06 | Stacked cards did not resemble the desktop workspace concepts | Added persistent rail/header and separate workspace views; moved invites/membership/deletion into Group | Desktop navigation, keyboard and draft-preservation checks |
| UX-07 | Chat history looked squeezed and Chat/Plan looked almost identical | Chat is now the default dedicated conversation view; Plan is separate. Composer is compact, grows to a bounded height, and has inline Send | Desktop checks require a wide chat and message history exceeding 55% of the panel height |
| UX-08 | Manage group was redundant in Trip overview | Removed overview and header management buttons; member context is read-only and management stays in Group | Browser check confirms no Manage group button in Trip overview |
| UX-09 | Private concerns lived on a separate page that was hard to reach, and the leader's own concerns also showed in the anonymous list | Concerns are a collapsible tile beside Chat (collapse remembered per browser, old `?view=concerns` links open Chat with it open); lists are newest first and scroll inside the tile; the leader's own concerns appear only under Your concerns, apart from From the group (anonymous) | Integration tests (own rows excluded from `anonymous`, newest first), unit tests, and desktop e2e at 1366 x 768 and 1920 x 1080 |
| REL-01 | Ambiguous message retries could duplicate discussion | UUID deduplication by sender/trip; different text with the same ID returns 409 | Concurrent API retries and browser simulation of a lost response after commit |
| PRIV-01 | New cached feature data could survive a demo-persona switch | Added preference/chat keys to the existing signed-in-state reset | Account-cache tests and membership/privacy checks |
| CI-01 | Native Biome rejected unused effect dependencies in the workspace and composer | Workspace explicitly compares the previous view before resetting scroll; composer uses draft content to reset its empty height while preserving auto-growth | Native Biome CLI, TypeScript, frontend tests and build; the earlier WASM-only check missed these diagnostics |

## Open issues and limitations

| Item | Status / impact | Next owner |
| --- | --- | --- |
| Live Pilot acceptance | Durable lifecycle, bounded Gateway research and private fit checks are implemented; real provider execution needs `AI_GATEWAY_API_KEY` and `PILOT_MODEL`. Sample/mocked results do not establish live success. | Planning / platform owner |
| Intended contribution verification | Personal member-to-leader route remains unproven; existing business-account experiments do not resolve it | Payment feasibility owner |
| Webhook reconciliation | Events are recorded, but full resource reconciliation/state transitions are absent | Payments owner, after agreed money design |
| Hosted demo availability | Production returned Service Suspended when checked earlier Nov 6; current branch has not been deployed | Platform owner using `docs/operations.md` |
| Secret rotation status | The earlier foundation report flags exposed staging vault/invite secrets; rotation status is not established by this work | Platform owner; verify without copying secrets into docs/logs |
| Judge access and demo reset | Judge login list is empty; reusable reset/quota fallback flow is incomplete | Demo/platform owner |
| Bundle size | Vite reports the existing >500 kB entry-chunk advisory; latest build is approximately 640 kB before gzip | Frontend performance follow-up |
| Cross-browser/mobile | Automated UI verification here is desktop Chromium at two sizes; no claim of phone or other-browser acceptance | Later verification scope |

## Verification evidence

| Check | Latest relevant result |
| --- | --- |
| Complete backend suite | 538 passed against isolated PostgreSQL 18 (`pytest -q`) |
| Complete frontend suite | 342 passed, including keyboard submission, privacy, cache invalidation, retry, navigation and the concerns tile |
| Desktop browser suite | 12 passed at 1366 x 768 and 1920 x 1080, including sample selection and two-member cancellation acceptance; combined run used the guarded disposable-database fixture |
| Type/static checks | Strict mypy, Ruff lint/format, TypeScript, whole-web Biome lint and changed-file formatting passed. Full Windows formatter check flags existing CRLF files |
| Migration chain | One Alembic head: `0008_planning`; fresh test-database upgrade exercised by integration tests |
| Production frontend build | Passed, with the bundle-size advisory above |

Local Python validation used PostgreSQL 18; repository CI uses PostgreSQL 16. The original
Biome 2.6.3 validation used the WebAssembly API when Windows blocked the native binary, but that
check missed two effect-dependency errors subsequently reported by CI. The correction was
validated with the native CLI using the exact `npm --prefix web run lint` command from CI.

These are local results. The existing CI workflow triggers on main pushes and pull requests, so
pushing a feature branch alone does not establish a new remote CI result. No production release
or promotion was performed.

Browser-test screenshots/reports and generated API files are intentionally ignored. Repeat with
`npm --prefix web test -- --run` and, against a running local demo stack,
`npm --prefix web run e2e -- --project desktop-laptop --project desktop-wide`.

The existing invite limiter allows 10 preview/join requests per IP per 60 seconds. Repeated demo
test runs can reach that limit; wait for the normal window rather than weakening it. Wait for
the local server to finish migrations/startup before starting a browser run.
