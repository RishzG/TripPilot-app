# TripPilot progress

Updated **November 6, 2026** (America/Chicago). This folder is the current implementation and
handoff record. `docs/planning/` retains the product decisions, roadmap and historical concepts.
When a concept differs from a later explicit user decision, the later decision wins.

- [Implementation status](implementation-status.md): what works, what is partial and what is missing.
- [Bugs and verification](bugs-and-verification.md): reported issues, fixes, open limitations and test evidence.
- [Parallel work streams](parallel-workstreams.md): independent teammate tasks, ownership and integration dependencies.
- [Manual testing](manual-testing.md): how to exercise the current desktop app.
- [Planning acceptance checklist](../planning/manual-test-planning.md): manual checks for the full planning slice and later priorities/opt-outs.
- [Planning workspace](planning-workspace.md): trip context, immutable plans, private Pilot fit checks and version-bound decisions.
- [Shared style guide](../style-guide.md): theme tokens, UI conventions and how to make visual changes.

## Current milestone

The group-workspace foundation is usable: create/join a trip, maintain private travel preferences,
exchange persisted live chat, manage membership and delete a workspace when only the organiser
remains active. The desktop shell has dedicated Chat, Plan, Preferences and Group views.

**Chat is the default conversation view. Plan now contains shared trip details, day itinerary/map,
version history, deterministic estimated shares and cancellation proposals.** Pilot uses private
constraints in separate per-member checks and returns owner-only explanations. Samples are clearly
labeled. See [the planning workspace](planning-workspace.md) for contracts, limits and setup.

The source implements the requested planning/replanning flow. Live research still needs an AI
Gateway key/model in both API and worker environments and an external-provider acceptance run.
Booking coordination, expense settlement and the desired personal-leader payment route remain
separate work; no new money movement is introduced.

## Branch and delivery

Implementation is on `codex/group-workspace`, fast-forwarded to `main` at `cf55863` before this planning slice, in
`RishzG/TripPilot-app`. These docs accompany that branch's workspace changes. The local demo runs
at `http://localhost:8000/demo`; a branch push is not a production deployment.

Update this folder when merging the next slice: identify changed behavior, evidence, limitations
and which work streams have become unblocked. Keep generated schemas, local database files,
credentials, caches and browser-test artifacts out of commits.
