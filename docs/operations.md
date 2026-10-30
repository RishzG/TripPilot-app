# Operations

How TripPilot is built, released and kept running. This file covers the hosted staging
environment (plan 01-07); the production procedure is in the "Production (01-17)" section below.

## Release pipeline

`.github/workflows/release.yml` (workflow `release`) runs on every push to `main` and can be
dispatched by hand. It never runs on pull requests.

1. `build-push` builds the Docker image once with `GIT_SHA=<commit sha>` and pushes
   `ghcr.io/rishzg/trippilot-app:<sha>` and the moving `:main` tag. The `:main` tag exists only so
   Render can create or resume the staging services; production pins a sha.
2. `deploy-staging` runs only when the repository variable `STAGING_BASE_URL` is set and the
   variable `STAGING_ACTIVE` is `true`. It posts the staging web and worker deploy hooks with
   `imgURL=ghcr.io/rishzg/trippilot-app:<sha>` and then polls `<STAGING_BASE_URL>/api/health`
   every 15 seconds for up to 10 minutes until `git_sha` equals the commit.

Image-backed Render services never redeploy on their own when a tag moves, so the deploy hooks are
the only deploy mechanism.

Migrations run once per deploy: the web service's pre-deploy command is
`python -m trippilot.db.migrate`, which takes a Postgres advisory lock (key 727001) before
`alembic upgrade head`, so concurrent runs queue up and the second one upgrades nothing. Render
runs the pre-deploy command for image services (confirmed on the first staging deploy,
2026-10-29). A brand-new Postgres can refuse connections for a short while after Render reports it
created, so the lock connection retries every 2 seconds for up to 60 seconds before the deploy
fails.

`GET /api/health` reports `status`, `git_sha`, `db`, `worker_last_seen_seconds` (age of the newest
worker heartbeat), `paypal_vault_scope` (true or false from the cached PayPal token, null when
PayPal cannot be asked) and `started_at` (UTC start time of the web process, which changes on every
restart).

## Staging power (UD-5)

Staging (web, worker and Postgres, all paid plans) is billed from the one-time $50 Render hackathon
credit, so it runs only while someone needs it and is suspended in between. Production is suspended
between uses only until Nov 5 (see "Production power" below).

**Who:** the Track B (platform) teammate owns staging power and checks at the end of each day that
staging is suspended. Any teammate may resume staging for staging work and must suspend it at the
end of that work session.

**Commands.** Put `RENDER_API_KEY`, `STAGING_BASE_URL`, `STAGING_WEB_SERVICE_ID`,
`STAGING_WORKER_SERVICE_ID` and `STAGING_DB_ID` in the git-ignored `.env.staging` at the repo root
(never commit it; the only GitHub copy of the key is the `production-power` environment secret,
which staging does not use). The script reads that file itself; variables
already set in the shell win, and `STAGING_ENV_FILE` points it at another file. Then:

```bash
uv run python scripts/ops/staging_power.py status
uv run python scripts/ops/staging_power.py resume
uv run python scripts/ops/staging_power.py suspend
uv run python scripts/ops/staging_power.py restart-proof --timeout 75
uv run python scripts/ops/staging_power.py env-keys
uv run python scripts/ops/staging_power.py set-env KEY VALUE
```

- `status` prints web, worker and database state; `staging: active` only when none of the three is
  suspended.
- `resume` resumes Postgres, then web, then worker, waits for `/api/health` to report the database
  ok, sets `STAGING_ACTIVE=true` and dispatches `release.yml` on `main` so the current main sha is
  deployed.
- `suspend` sets `STAGING_ACTIVE=false` first, then suspends worker, web and Postgres.
- `restart-proof` creates a smoke trip, restarts web and worker, waits for a new `started_at` and a
  worker heartbeat under 60 seconds, then reads the trip back. Non-zero exit on any failure.
- `env-keys` lists the environment variable names (never values) set on web and worker.
- `set-env KEY VALUE` sets one variable on both web and worker. **A Render restart does not apply a
  changed variable; only a new deploy does** (found 2026-10-29 setting `PAYPAL_WEBHOOK_ID`). After
  `set-env`, redeploy the current main with
  `gh workflow run release.yml --repo RishzG/TripPilot-app --ref main` (staging resumed), then check
  the change took effect.

## Staging PayPal webhook (01-13)

The staging sandbox app has one webhook, id `0Y2839891X535641R`, for
`https://trippilot-staging-web.onrender.com/api/paypal/webhooks`, subscribed to the authorization,
capture, order, payout, vault and consent-revoked event types (registered 2026-10-29 by
`scripts/spikes/register_webhook.py`, which reuses the webhook for an exact URL instead of creating
a second one). Its id is `PAYPAL_WEBHOOK_ID` on both staging services. Without it the endpoint
answers 503 and PayPal retries for up to 3 days; an unsigned request answers 400
`verification_failed`.

The script runs `gh` against `RishzG/TripPilot-app` explicitly (this checkout's default `gh`
repository is the wrong upstream); set `GH_REPO` to override it.

**While staging is suspended:** merges to `main` still build and push the image (production
promotion is unaffected) and `deploy-staging` is skipped by its job condition. Resuming staging
deploys the current main sha (D-50 under UD-5).

**Proofs that need staging** run only inside a resumed window: restart persistence (01-07), the Log
in with PayPal redirect (01-12), webhook registration and deliveries (01-13 and 01-14) and pool
enrolment. PayPal retries failed webhook deliveries for 3 days, so a suspended window does not lose
events, but nothing is processed until staging is back.

Spend alert: no alert available; Track B checks Render billing every Monday.

Render's Hobby workspace offers no spend or credit-usage notification (checked 2026-10-29: Billing
has Plan, Payment Method, Included Usage, Unbilled Charges and Credit Balance only). The Monday
check: Billing -> Credit Balance (what is left of the one-time $50 credit) and Unbilled Charges
(this month so far); below about $10 left, tell the team and make sure staging is suspended. The
build pipeline keeps its $0 spend limit (500 free minutes cover the pre-deploy migrations), so
build minutes can never be charged. Hobby workspaces cannot add team members, so Render access
stays with the workspace owner.

The staging database has a 1 GB disk (`diskSizeGB: 1`; Render's Basic tier defaults to 15 GB and
disks can grow but never shrink). The Postgres storage charge while suspended is confirmed from
Render billing after the first suspension.

**Restart caveat (found 2026-10-29):** a Render restart requested within about 2 minutes of a deploy
can be dropped, so `restart-proof` may report that `started_at` never changed. Wait a couple of
minutes after a deploy (or after resuming) and run `restart-proof` again before treating it as a
failure.

## Production (01-17)

Production is `trippilot-production-web`, `trippilot-production-worker` and
`trippilot-production-db`, created from `render.production.yaml` (a second Blueprint, Blueprint Path
`render.production.yaml`, **Auto Sync set to No** right after creation). It has its own PayPal
sandbox app, database, webhook id, `VAULT_KEYS` and `INVITE_SECRET`; none of them are shared with
staging (UD-1). `DEMO_MODE` is on (D-52).

**Production power (UD-5, changed 2026-10-30).** Until **Nov 5** production is suspended between uses,
like staging, to save the Render credit (about $0.67 a day). From Nov 5 it stays up through Dec 21
for the hosted checkpoint, the demo video and judging, and the power script refuses to suspend it
(only a local `--force` overrides that, for an emergency). Suspending keeps the database, so enrolled
pool buyers and their vault tokens survive.

Any teammate can turn it on or off from GitHub, without a Render account: Actions, then
`production-power`, then Run workflow with `status`, `resume` or `suspend`, or

```bash
gh workflow run production-power.yml --repo RishzG/TripPilot-app --ref main -f action=resume
```

`resume` turns Postgres, web and worker on with the image production last ran and waits for
`/api/health`; it never deploys. **Whoever resumes production suspends it when done** (until Nov 5).
Resume before promoting: `promote` waits for health and fails on a suspended service. The workflow
runs in the GitHub Environment `production-power` (protected branches only, no reviewer), which
holds the owner's Render API key as the secret `RENDER_API_KEY` and the resource ids as the
environment variables `PRODUCTION_WEB_SERVICE_ID`, `PRODUCTION_WORKER_SERVICE_ID` and
`PRODUCTION_DB_ID`. Render Hobby has no team members, so this is the only way teammates can power
production; the key is account-wide, so the environment is limited to `main` and the key reaches
only the step that runs the script. The owner can run the same commands locally:

```bash
uv run python scripts/ops/staging_power.py --target production status
uv run python scripts/ops/staging_power.py --target production resume
uv run python scripts/ops/staging_power.py --target production suspend
```

which read `RENDER_API_KEY`, `PRODUCTION_BASE_URL`, `PRODUCTION_WEB_SERVICE_ID`,
`PRODUCTION_WORKER_SERVICE_ID` and `PRODUCTION_DB_ID` from the git-ignored `.env.production`
(another path with `PRODUCTION_ENV_FILE`). `env-keys`, `set-env`, `logs`, `run-job` and
`restart-proof` take `--target production` too.

The Blueprint pins both services to `ghcr.io/rishzg/trippilot-app:<40-character sha>`, the creation
baseline that already ran on staging. It never names `:main` or another moving tag. After creation
the image that actually runs is whatever the last approved promotion deployed; the pinned sha in the
file is only the starting point.

**Promote (the only way to deploy production).** Pick a sha that is on `main`, has a `release` build
and has been verified on staging, then:

```bash
gh workflow run promote.yml --repo RishzG/TripPilot-app --ref main -f sha=<40-character sha>
```

Open the run in GitHub (Actions, then the run, then Review deployments) and approve the pending
`production` deployment as the required reviewer. Only after approval does the job run: it checks the
sha is 40 hex characters and an ancestor of `origin/main`, checks `docker manifest inspect` finds the
image, posts the production web and worker deploy hooks with `imgURL=ghcr.io/rishzg/trippilot-app:<sha>`
(environment secrets `RENDER_PRODUCTION_WEB_DEPLOY_HOOK` and `RENDER_PRODUCTION_WORKER_DEPLOY_HOOK`)
and polls `<PRODUCTION_BASE_URL>/api/health` for up to 10 minutes until `git_sha` equals the sha
(`PRODUCTION_BASE_URL` is a repository variable).

**Rollback** is the same command with the previous sha. Check first that the previous image works
with the current database schema (migrations only move forward).

**Never use Render's Manual Deploy or Manual Sync on production.** They skip the approval gate and
can only redeploy the sha pinned in `render.production.yaml`, which would silently roll production
back to the creation baseline.

**Environment variable changes need a redeploy.** Render applies a changed variable only on a new
deploy, not on a restart (same finding as staging). After changing a production variable, promote the
sha production is already running (read it from `/api/health`) and approve it.

**Freeze:** production is frozen from Nov 8 except for hotfixes (D-50). A hotfix goes through staging
and `promote` like any other change.
