# Operations

How TripPilot is built, released and kept running. This file covers the hosted staging
environment (plan 01-07); the production procedure is added by plan 01-17.

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
`alembic upgrade head`, so concurrent runs queue up and the second one upgrades nothing. If a
Render deploy turns out to ignore the pre-deploy command for image services, the fallback is to
run the same module in the web start command before uvicorn (the lock makes that safe).

`GET /api/health` reports `status`, `git_sha`, `db`, `worker_last_seen_seconds` (age of the newest
worker heartbeat), `paypal_vault_scope` (true or false from the cached PayPal token, null when
PayPal cannot be asked) and `started_at` (UTC start time of the web process, which changes on every
restart).

## Staging power (UD-5)

Staging (web, worker and Postgres, all paid plans) is billed from the one-time $50 Render hackathon
credit, so it runs only while someone needs it and is suspended in between. Production is never
suspended.

**Who:** the Track B (platform) teammate owns staging power and checks at the end of each day that
staging is suspended. Any teammate may resume staging for staging work and must suspend it at the
end of that work session.

**Commands.** Put `RENDER_API_KEY`, `STAGING_BASE_URL`, `STAGING_WEB_SERVICE_ID`,
`STAGING_WORKER_SERVICE_ID` and `STAGING_DB_ID` in the git-ignored `.env.staging` (never commit it,
never make the key a GitHub secret), then:

```bash
set -a; . ./.env.staging; set +a
uv run python scripts/ops/staging_power.py status
uv run python scripts/ops/staging_power.py resume
uv run python scripts/ops/staging_power.py suspend
uv run python scripts/ops/staging_power.py restart-proof --timeout 75
```

- `status` prints web, worker and database state; `staging: active` only when none of the three is
  suspended.
- `resume` resumes Postgres, then web, then worker, waits for `/api/health` to report the database
  ok, sets `STAGING_ACTIVE=true` and dispatches `release.yml` on `main` so the current main sha is
  deployed.
- `suspend` sets `STAGING_ACTIVE=false` first, then suspends worker, web and Postgres.
- `restart-proof` creates a smoke trip, restarts web and worker, waits for a new `started_at` and a
  worker heartbeat under 60 seconds, then reads the trip back. Non-zero exit on any failure.

The script runs `gh` against `RishzG/TripPilot-app` explicitly (this checkout's default `gh`
repository is the wrong upstream); set `GH_REPO` to override it.

**While staging is suspended:** merges to `main` still build and push the image (production
promotion is unaffected) and `deploy-staging` is skipped by its job condition. Resuming staging
deploys the current main sha (D-50 under UD-5).

**Proofs that need staging** run only inside a resumed window: restart persistence (01-07), the Log
in with PayPal redirect (01-12), webhook registration and deliveries (01-13 and 01-14) and pool
enrolment. PayPal retries failed webhook deliveries for 3 days, so a suspended window does not lose
events, but nothing is processed until staging is back.

Spend alert: pending (filled by 01-07 Task 3)

The Postgres storage charge while suspended is confirmed from Render billing after the first
suspension.
