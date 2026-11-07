# TripPilot planning and replanning handoff

Updated **7 November 2026** for `codex/activity-replanning`, based on `main` at `cf55863`.
This branch builds on the group workspace, live chat, private preferences and private concerns
already present at that baseline.

## What this branch adds

| Change | Where to try it | Commit |
| --- | --- | --- |
| **Versioned itineraries and cost splits** | In **Plan**, create a draft or revise the latest one. Add dated activities and choose their participants. Browse previous versions and see the original per-person estimates. The server allocates whole USD cents and distributes any remainder deterministically. | `9689096` |
| **Trip details and Pilot preview** | In **Plan → Set trip details**, save destination, dates and timezone. Members can also see them in **Trip overview**. **Start Pilot** queues a job that uses recent group-chat topics to pick activities from a curated London catalogue and saves a new draft with source links and price-check dates. | `7ec9258` |
| **Chat layout** | In **Chat**, outgoing messages sit on the right. Incoming messages sit on the left with the sender’s name and avatar. Each bubble contains its time and each day has a shared date header. | `4bc1858`, `bd3bc6f` |
| **Single-activity replanning** | In **Plan → Current plan & replacements**, the organiser selects a draft as current and proposes a replacement. Affected members compare the activity, date, participants and estimated shares before responding. An opt-out recalculates the split and resets approvals. The last required acceptance applies the revision and preserves the prior version. | `94c26ce` |

Pilot is a London-only preview that matches keywords locally against official venue information.
It reads group chat and leaves private preferences and concerns outside the run. It distinguishes
free admission from an unknown estimate. Replanning covers one activity at a time and requires
explicit acceptance from the affected members who remain in the proposal. Booking, payment,
settlement and deadline-based approval are outside this branch’s scope.

## Run the local demo

From the checkout, run `docker compose up --build` and open
[the demo](http://localhost:8000/demo). The stack includes PostgreSQL, the app and the worker
required by Pilot. The Compose configuration uses fake PayPal. If using an existing local
preview, use its configured port instead.

Use three separate browser profiles or contexts so the personas keep separate session cookies.
Sign in as **Maya**, create a trip, and copy its invite link from **Group**. Sign in as **Sam**
and **Ana** in their own sessions and use the link to join. Start a fresh trip for this checklist.

## Manual test checklist

### Chat

- [ ] Send a message as Maya and reply as Sam. In each session, the signed-in person’s own
  message is on the right without a name or avatar. The incoming message is on the left with
  the sender’s name and avatar.
- [ ] Send multiple messages on the same day. Verify one date header above the messages and
  a time inside each bubble. Reload and confirm the history and sides are preserved.

### Trip details and Pilot

- [ ] As Maya, open **Plan → Set trip details** and save **London**, **1–2 December 2026**,
  and **Europe/London**. Confirm the saved details appear in **Trip overview**.
- [ ] Send `Art, fashion and design, then a park walk` in **Chat**. Click **Start Pilot**
  in **Plan**, then open the saved draft when the run is ready.
- [ ] Verify the draft includes **V&A South Kensington** and **Hyde Park lakeside walk**.
  Check the source links and checked dates. V&A general admission shows **$0.00** and the
  unpriced Hyde Park activity shows **Estimate pending**.
- [ ] Reload as Sam. The draft remains visible. Only the organiser has controls to change trip
  details or start Pilot.

### Itinerary history and cost splits

- [ ] As Maya, use **Revise itinerary** on the latest draft. Add **Museum visit** with a
  **$0.00** estimate and **Dinner** with a **$12.01** estimate. Assign all three members to
  both activities and save a new draft version.
- [ ] Verify Dinner splits into **$4.01, $4.00 and $4.00**. Confirm Sam and Ana see the same
  saved shares.
- [ ] Click **Previous**. The earlier Pilot draft retains its original activities and estimates.
  Return to the latest draft.

### Replacement approvals

- [ ] As Maya, click **Set as current plan** on the version with Museum visit. Choose
  **Propose activity replacement**, replace Museum visit with **Guided tour**, enter
  **$100.01**, and include all three members.
- [ ] In each session, check the side-by-side comparison and per-person shares. The tour starts
  with shares of **$33.34, $33.34 and $33.33**. Museum visit is still on the current plan.
- [ ] As Maya, click **Accept revision**. Check **1 of 3** accepted. As Sam, click
  **Opt out of activity**. The proposal should now exclude Sam, show **$50.00 and $50.01**
  for the remaining members, and reset approvals to **0 of 2**.
- [ ] Have Ana accept the revised proposal. Museum visit stays current. Have Maya accept again.
  Guided tour becomes current and Dinner stays the same.
- [ ] Open the previous version and confirm it still shows Museum visit with all three original
  participants.

### Edge cases

- [ ] **Withdrawal.** As Maya, submit another replacement and click **Withdraw proposal**.
  Verify the current plan stays the same.
- [ ] **Last participant opts out.** In a solo trip, select a plan and propose a replacement for
  Maya alone. Opt out. The proposal closes and the original activity stays current.
- [ ] **Invalid input.** Try an end date before the start date or a negative activity estimate.
  Saving fails and the previous saved values are preserved.

## Verification on this branch

- **Backend** — 529 pytest tests passed against an isolated PostgreSQL database. Ruff, strict
  mypy and the Alembic single-head check passed. The migration head is
  `0010_activity_replanning`.
- **Frontend** — 337 Vitest tests passed. TypeScript, Biome and the production build passed.
- **Browser** — The Pilot and three-person replanning scenarios passed at 1366×768 and
  1920×1080. The chat and itinerary flows were also exercised during their respective changes.

These are local results. The branch is intended for review and has no production deployment
associated with this handoff.
