# trippilot
AI-powered group trip planning and coordinated payments

## Try it as a judge

Coming soon. The hosted production URL and the public sandbox judge logins are added here when the
production environment goes live (plan 01-17). Real PayPal accounts do not work in the sandbox, and
no credentials are published until then.

## Deployments

Two hosted environments, each with its own PayPal sandbox app, database, webhook and encryption keys
(the Blueprints are `render.yaml` for staging and `render.production.yaml` for production).

- **Staging** deploys automatically on every merge to `main` while it is resumed (the `release`
  workflow builds `ghcr.io/rishzg/trippilot-app:<sha>` once and deploys exactly that sha). It is
  suspended between uses to protect the hosting credit; see [docs/operations.md](docs/operations.md).
- **Production** is deployed only by the `promote` workflow, pinned to a full commit sha that is on
  `main` and has already run on staging. A required reviewer must approve the run in GitHub
  (Actions, then Review deployments) before anything is deployed. The production Blueprint has Auto
  Sync off, so a merge never reaches production on its own, and Render's Manual Deploy and Manual
  Sync are not used on production.
- **Rollback** is the same workflow with the previous sha:
  `gh workflow run promote.yml --repo RishzG/TripPilot-app --ref main -f sha=<40-character sha>`.
- Production is frozen from Nov 8 except for hotfixes (D-50).
