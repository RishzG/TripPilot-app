# Morning group walkthrough

Use disposable demo trips. Each teammate needs a separate browser profile or private window;
normal tabs share a persona cookie. Start at `/demo`. Maya leads; Sam and Ana join using
Maya's Group invite. Do not switch personas within the same browser profile during the run.

1. Maya creates a trip, shares the invite, and checks that everyone appears in Group.
2. Each member saves Preferences: one Must have and one Prefer, plus an optional budget.
   Reopen the form to check persistence. Other members must not see these private fields.
3. Maya saves Chicago and a one-day date range in Plan, loads the Chicago sample, chooses
   Chicago sample day, and selects it for the demo. Samples bypass private fit checks.
4. Everyone reviews day controls, location buttons, source links, activity shares and the
   itinerary total. Location buttons move the single map marker; they do not show routes.
5. Maya chooses Cancel / find alternatives for Art Institute and proposes Cultural Center.
   Sam chooses Needs discussion, Reject, or Request another alternative. Apply must remain
   disabled. Discuss the concern in Chat without copying another person's private inputs.
6. Maya proposes the alternative again. Responses start empty on the new revision. Everyone
   affected accepts that exact revision, then Maya applies it. Review the original in history
   and compare its group total and changed activities with the selected revision.
7. In a fresh demo trip with the paid sample selected (before replacing Art Institute),
   Sam chooses Propose my opt-out on the paid activity. The activity's total stays fixed;
   remaining participants carry its cost. Review each member's difference. All affected
   members, including Sam, accept before Maya applies it. No booking or refund is implied.
8. Save a changed requirement after proposing a change. The old proposal must become stale;
   it cannot be applied. The final participant cannot opt out of an activity through this flow.

Record the persona, action, expected result, actual result and browser size for each issue.
Ask whether the day label, active map marker, daily/group totals and revision comparison are
clear. Record feedback before choosing further UI changes. The teammate walkthrough remains
pending until the group performs it.

Live Pilot requires configured API and worker credentials. Use the evaluation cases separately;
sample success is not evidence of live provider quality. Apply migration 0009 before running
the new preference form against an existing database.


Use the [full planning acceptance checklist](manual-test-planning.md) for dates/timezone editing,
immutable history and exact shares, multi-day/map review, durable worker recovery, private
explanations, and cancellation acceptance. It includes prerequisites and a results table.
