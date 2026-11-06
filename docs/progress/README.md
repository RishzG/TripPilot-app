# TripPilot progress

Updated **November 6, 2026** (America/Chicago). This folder is the current implementation and
handoff record. `docs/planning/` retains the product decisions, roadmap and historical concepts.
When a concept differs from a later explicit user decision, the later decision wins.

- [Implementation status](implementation-status.md): what works, what is partial and what is missing.
- [Bugs and verification](bugs-and-verification.md): reported issues, fixes, open limitations and test evidence.
- [Parallel work streams](parallel-workstreams.md): independent teammate tasks, ownership and integration dependencies.
- [Manual testing](manual-testing.md): how to exercise the current desktop app.

## Current milestone

The group-workspace foundation is usable: create/join a trip, maintain private travel preferences,
exchange persisted live chat, manage membership and delete a workspace when only the organiser
remains active. The desktop shell has dedicated Chat, Plan, Preferences and Group views.

**Chat is the default conversation view. Plan is a separate itinerary/map view with an explicit
empty state.** Preferences and group management are not part of the chat canvas. This separation
implements the user's latest UX feedback; the older side-by-side concept remains design history.

This does **not** complete the planning/replanning milestone. Pilot, sourced travel research,
plan versions, private concerns, booking coordination and expense settlement still need work.
The desired member-to-personal-leader payment route remains unproven; no fallback was selected.

## Branch and delivery

Implementation is on `codex/group-workspace`, based on `main` at `a1d5eef`, in
`RishzG/TripPilot-app`. These docs accompany that branch's workspace changes. The local demo runs
at `http://localhost:8000/demo`; a branch push is not a production deployment.

Update this folder when merging the next slice: identify changed behavior, evidence, limitations
and which work streams have become unblocked. Keep generated schemas, local database files,
credentials, caches and browser-test artifacts out of commits.
