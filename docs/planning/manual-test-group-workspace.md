# Manual test: group workspace

**Archived checklist.** Use the updated [manual tests](../progress/manual-testing.md) for the
current dedicated Chat/Plan views. This file preserves the intermediate workspace test notes.

Use the local demo at `http://localhost:8000/demo`. Refresh once after a new build. Use a regular
browser window for Maya and a private window or a different browser for Sam; two normal tabs
share their sign-in cookie. Create disposable test trips rather than changing a real workspace.

## 0. Desktop workspace navigation

1. Open or create a trip at a laptop/desktop window size. The sidebar and trip header stay
   visible. **Plan** opens chat beside an honest empty itinerary/map panel; **Chat** gives
   the conversation more room. The composer and its Send action should fit at 1366 x 768.
2. Type an unsent chat message. Visit **Preferences**, **Group**, then **Chat**. The draft
   should still be there. Unsaved preference edits also survive changing workspace views.
3. **Preferences** contains your form and the expandable shared summary. **Group** contains
   the member list, organiser invite controls, leave/removal and delete actions.
4. **Bookings** and **Splits** are marked Soon and show explicit unavailable states. They must
   not show invented bookings, balances or payment success. **Trip overview** summarizes the
   current group. **All trips**, **Account** and **Switch demo persona** open their real routes.
5. Reload while in Preferences or Group. The selected view should remain selected through
   the URL. Browser Back should return to the previous view. Keyboard Tab/Enter should operate
   navigation and controls with visible focus and no horizontal overflow.

## 1. Empty fields and saved preferences

1. Continue as Maya and create a trip named `Manual preferences check`. Choose **Preferences**.
2. The starting-city, interests and budget fields are empty. Light italic text prefixed `Ex.`
   is a hint, not a saved value. Leave them empty and save: the group summary should still say
   `Starting city not shared` and `No interests shared yet` when you return to Preferences.
3. Enter `Chicago`, `Museums and easy walks`, relaxed pace, `421.37` USD and a made-up dietary
   note. Save: the workspace should switch to **Chat**, focus the conversation and show a saved
   confirmation. Return through **Preferences** in the sidebar and expand
   **Group preferences**. The city, interests and pace should update
   immediately. Budget and dietary notes must not appear in the group summary.
4. Refresh. The fields should retain the entered values. Change the city and save again;
   the summary should show the new city without a refresh.
5. Try `-1`: Save should say `Budget cannot be negative.` Try `12.345`: Save should ask for
   up to two decimal places. Try `0`: it
   should save as zero. Clear budget and save: refreshing should show an empty field again.

## 2. Joining, privacy and live updates

1. Open **Group** and copy Maya's invite link. In the other browser window continue as Sam,
   open the invite and join.
2. Maya should see Sam join without refreshing. **Delete workspace** remains visible but disabled
   with an explanation that the other members must leave or be removed. Sam has no delete action.
3. Open **Preferences** as each person. Sam must see empty private budget/dietary fields for
   their own profile, not Maya's values.
   The group summary should show Maya's city, interests and pace only.
4. Save different preferences as Sam. Maya's group summary should update without a refresh;
   Maya's own form and private values should remain unchanged.
5. Create another trip: preferences should start empty there. They belong to a trip, not all trips.

## 3. Deleting an unused workspace

1. Create a separate disposable trip and do not let anyone else join it.
2. Open **Group**. Choose **Delete workspace**, then **Keep workspace**. It should remain intact.
3. Choose **Delete workspace**, then **Yes, delete workspace**. You should return to My trips,
   and the workspace should disappear. Its saved trip URL and invite link should stop working.
4. In the shared trip from test 2, have Sam leave or remove Sam as Maya. Once Maya is the only
   active member, **Delete workspace** should become enabled without refreshing. Test both
   leaving and removal with separate disposable trips. If another active member remains,
   deletion must stay disabled. Confirming deletion should return Maya to My trips.

## 4. Group chat

1. Create a disposable trip as Maya and join as Sam in the separate browser window.
2. Send a multiline message as Maya. Sam should see it without refreshing, with Maya's name
   and a timestamp. Reply as Sam and confirm Maya sees the reply live.
3. Refresh both windows. The conversation should persist in the same order.
4. Enter only spaces or a newline. Send should remain disabled. Enter can add a newline;
   sending requires the **Send message** button. Messages have a 4,000-character limit.
5. Temporarily disconnect the browser's network and try sending. The error should keep the
   draft. Reconnect and retry: the message should appear once. The automated desktop test
   also covers a server-committed message whose response was lost.
6. With more than 30 messages, choose **Load older messages**. Older discussion should appear
   above recent messages without duplicates. Scroll down to return to the latest messages.
7. Have Sam leave or remove Sam as Maya. Sam must no longer be able to read or send chat in
   this trip. Existing messages remain visible to Maya until the workspace is deleted.
8. Switch demo personas in the same browser and return to an authorized trip. Another persona's
   cached conversation must not appear before the current account's authorized history loads.

Scope: preferences, group chat and workspace deletion. Private concerns, explicit Pilot requests,
AI planning, booking and payment execution remain for later slices. `/plan` in chat is ordinary
text until the explicit planning-request feature is implemented.
