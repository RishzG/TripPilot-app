# Manual testing: current desktop workspace

Updated November 6, 2026. Use `http://localhost:8000/demo` and refresh after a new build.
For two people, use a normal browser window for Maya and a private window or a different browser
for Sam. Two normal tabs share the same sign-in cookie. Create disposable test trips.

## Navigation and layout

1. Continue as Maya and create a trip. **Chat** is the default view. It should show a wide
   conversation panel with a compact composer at the bottom, not the itinerary beside it.
2. Select **Plan**: only the empty itinerary/map view should appear. **Open group chat** returns
   to Chat. There is no generated itinerary yet.
3. Type an unsent message, then visit Preferences and Group. Return to Chat: the draft remains.
   Unsaved preference edits should also survive view changes. Reloading does not promise to
   preserve unsent drafts; saved data does persist.
4. Trip overview is read-only group/trip context, without a Manage group action. Membership,
   invites and workspace deletion belong in **Group**.
5. Bookings and Splits are marked Soon and show unavailable states. All trips, Account and
   Switch demo persona lead to their real routes. Reload retains the selected view through
   the URL; browser Back returns to the preceding view.
6. At 1366 x 768 and 1920 x 1080, check visible focus with Tab/Enter, readable controls and no
   horizontal overflow. Chat history should take most of the panel height and scroll separately
   from its composer. A multiline draft grows to a bounded height rather than hiding history.

## Saving preferences

1. Open **Preferences**. Light italic `Ex.` text is a placeholder, not an entered value.
2. Leave fields empty and save, then reopen Preferences and expand **Group preferences**.
   Empty city/interests should remain `Starting city not shared` / `No interests shared yet`.
3. Enter `Chicago`, `Museums and easy walks`, relaxed pace, `421.37` USD and a made-up dietary
   note. Save should select/focus Chat and show a saved confirmation. Reopen Preferences: the
   public summary updates, while budget/dietary notes remain outside that summary.
4. Refresh in Preferences: saved values remain. Edit/save again and inspect the new summary.
5. Budget `-1` should say `Budget cannot be negative.` `12.345` should request up to two decimal
   places. `0` saves as zero. Clearing the field saves an unspecified budget and stays empty
   after refresh. Do not mistake an example hint for saved budget data.

## Joining, privacy and membership

1. As Maya, open **Group** and copy the invite. In the other browser continue as Sam, open the
   invite and join. Maya should see the member count/list update without a refresh.
2. Delete workspace remains visible to Maya but disabled while Sam is active. Sam has no delete
   action. Sam cannot reset the organiser's invite or manage other members.
3. Open Preferences as each person. Sam must not see Maya's private budget/dietary values. The
   shared summary contains only each member's city, interests and pace.
4. Save different preferences as Sam. Maya's expanded public summary updates live; Maya's own
   form/private values stay unchanged. Another trip starts with its own empty preferences.
5. Test leave and organiser removal using Group. Removed members cannot use the invite to rejoin
   until the organiser adds them back; re-added members should appear live again.

## Chat persistence and retries

1. In Chat, send a multiline message as Maya. Sam should see it live, with Maya's name/time.
   Reply as Sam, then refresh both windows: both messages remain in chronological order.
2. Blank/whitespace-only input cannot be sent. Enter adds a line. **Send message** or
   Ctrl/Command+Enter sends. The limit is 4,000 characters.
3. Disconnect the browser network and try to send. The error retains the draft. Reconnect and
   retry: one message should be recorded. Automated tests also simulate a committed POST whose
   response is lost, to verify deduplication in that harder case.
4. With over 30 messages, use Load older messages. Earlier discussion appears above recent
   messages without duplicates. Scrolling up should not be interrupted by new arrivals.
5. After Sam leaves/is removed, Sam cannot read or send messages in the trip. Maya still sees
   existing history. Switching demo personas must not briefly show another person's cached trip
   data before the current authorised view loads.

## Deleting an eligible workspace

1. Create a separate disposable trip. In Group choose Delete workspace, then Keep workspace:
   it remains intact. Confirm deletion on a second attempt: you return to All trips, the row is
   gone, and the old trip URL/invite no longer works.
2. In a shared disposable trip, have every other member leave or be removed. Delete should
   become enabled for the organiser without refreshing. If any other active member remains,
   it must stay disabled. Re-adding a member blocks deletion again.

Scope: public chat, preferences, membership, workspace UX and private concerns. Private concerns
have their own checklist:
[manual test: private concerns](../planning/manual-test-private-concerns.md).
A working Pilot, plans/maps, booking and money features are not yet implemented. `/plan` typed
into chat remains ordinary text.

For a fresh local stack, the existing `docker compose up --build` recipe starts PostgreSQL,
the app and the worker with demo mode and fake payments. The desktop browser suite runs with
`npm --prefix web run e2e -- --project desktop-laptop --project desktop-wide` after the stack is
ready. Repeated invite tests can hit the normal 10-per-minute preview/join limiter.
