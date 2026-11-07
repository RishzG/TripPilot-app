# Manual test: private concerns

Written November 6, 2026 for branch `feat/private-concerns` (stage 3 of the
[feature map](feature-map-and-architecture.md)). It covers private concerns only. The Pilot
request lifecycle is not on this branch: it is built on `feat/stage-3-concerns-pilot-runs` and is
pending. Here, `/plan` typed into chat is ordinary text and is sent as a message. Group chat,
preferences, membership and deletion are covered by the
[current manual tests](../progress/manual-testing.md); run those too if this branch touched them.

Nothing here calls an AI model, a travel provider or PayPal.

## Setup

1. Start the local stack:

   ```sh
   docker compose up --build
   ```

   It runs PostgreSQL, the app on `http://localhost:8000` and the worker, with demo mode and fake
   payments. Wait until the app logs that startup and migrations are finished.
2. Open `http://localhost:8000/demo` and refresh once after a new build.
3. You need **three people** to check who can see what. Each needs its own sign-in cookie, so use
   three separate windows that don't share cookies: for example a normal Chrome window (Maya), a
   Chrome incognito window (Sam) and a different browser (Ana). Two tabs in the same window share
   one sign-in.
4. As Maya, create a disposable trip, for example `Manual concerns check`. Maya is the **leader**.
   Share the invite from **Group**; Sam and Ana join as members.

## 1. Sending a private concern

1. As Sam, open **Chat**. The **Private concerns** tile is to the right of the chat (below it
   on a narrow window). It explains that the leader sees the text without your name, and that in
   a small group anonymity can't be absolute. There is no **Private concerns** entry in the
   sidebar.
2. The `Ex.` text in the box is a hint, not saved content. With the box empty or only spaces,
   **Send privately** can't be used.
3. Type `The boat tour is more than I want to spend` and choose **Send privately**. It appears
   in Sam's own list with **Withdraw**.
4. Refresh Sam's window. The concern is still there.
5. Type more than 1,000 characters. You can't send it (the limit is 1,000).
6. Optional: an author can have up to 20 open concerns. The 21st is refused with
   `You can have up to 20 open concerns. Withdraw one to add another.`

## 2. The tile: collapse, memory, focus and scrolling

1. Choose the panel button at the top right of the tile (**Collapse private concerns**). The tile
   becomes a slim strip and the chat widens to take the space. Choose **Expand private
   concerns** to bring it back; anything you had typed in the box is still there.
2. Collapse the tile and refresh. It stays collapsed in this browser. Choose **Share something
   privately** under the chat title: the tile opens and the cursor is in the box.
3. Open an old link that ends in `?view=concerns` (for example
   `http://localhost:8000/trips/<id>?view=concerns`). It opens **Chat** with the tile open, and
   the address bar drops the `?view=concerns` part.
4. As Sam, send five or six concerns. The page itself never scrolls. Each list in the tile shows
   about two or three items, newest first, and scrolls inside itself; the box and **Send
   privately** stay at the top of the tile.
5. Type `/plan` in the chat and send it. It is posted as an ordinary message that everyone in
   the trip can read; nothing starts and nothing is blocked.

## 3. Who can see a concern

This is the most important part. Keep all three windows open on the trip, without refreshing.

1. **Maya (leader)** sees Sam's text appear under **From the group (anonymous)** in the
   **Private concerns** tile without refreshing. It shows **only the text and the date**: no
   name, avatar, exact time or anything else that points to Sam.
2. **Ana (member)** sees no one else's concerns: only an empty own list and the box to send one.
   She doesn't see a count of other people's concerns either.
3. As Ana, send a concern. Maya's **From the group (anonymous)** list now has two entries,
   newest first, still without names. Sam's own list still shows only Sam's concern.
4. As Maya, send a concern too. It appears only under **Your concerns**, with a **You** badge
   and **Withdraw**. It never appears under **From the group (anonymous)**.
5. **Developer check (optional):** in Ana's window, open DevTools, **Network**, and look at:
   - the `/api/trips/<id>/concerns` response: `mine` holds only Ana's concerns and `anonymous` is
     `null`
   - the `/events` stream: `concerns.changed` events have empty data (`{}`), with no text or IDs

   In Maya's window, the `anonymous` items have only `content` and `submitted_on`, with no
   account ID, name or client ID.

## 4. Withdrawing a concern

1. As Sam, choose **Withdraw** on Sam's concern. It leaves Sam's list.
2. Without refreshing, it also leaves Maya's **From the group (anonymous)** list. The others
   stay.
3. Refresh both windows. The withdrawn concern doesn't come back.
4. Sam can't withdraw someone else's concern; there is no control for it.

## 5. Members who leave or are removed

1. In a fresh disposable trip, have Ana send a concern, then have Ana leave the trip (or remove
   her as Maya in **Group**).
2. Ana can no longer open the trip or its concerns.
3. Ana's concern **stays** in Maya's **From the group (anonymous)** list. This is deliberate: if
   it disappeared at the moment Ana left, Maya would learn who wrote it. Ana can't withdraw it
   after leaving.
4. If you would rather a departed member's concerns be deleted, raise it: this rule was a design
   choice made during planning and can be changed.

## 6. Switching accounts

1. In one window, view a trip as Maya with concerns visible, then use **Switch demo persona** to
   become Ana and open the same trip.
2. Maya's **From the group (anonymous)** list and her own concerns must not show, even for a
   moment, before Ana's own view loads.

## Automated check

`web/e2e/private-concerns.spec.ts` covers the core of sections 1, 3 and 4 with three real
browser sessions against the running stack, including the live updates and the leader's
**Your concerns** / **From the group (anonymous)** split. `web/e2e/workspace-layout.spec.ts`
covers section 2: the tile layout (chat width open and collapsed), scrolling inside the tile,
the memory across a reload, the old `?view=concerns` link and the focus from **Share something
privately**. Rebuild the stack first so it runs the current code, then run them one at a time:

```sh
docker compose up --build -d --wait app worker
npm --prefix web exec -- playwright test e2e/private-concerns.spec.ts --project=desktop-laptop
npm --prefix web exec -- playwright test e2e/workspace-layout.spec.ts --project=desktop-laptop
```

Run one window size at a time: each run joins two people, and back-to-back runs can hit the
normal limit of 10 invite previews/joins per minute. The manual sections still matter for what
the test doesn't cover: departed members and account switching.

## Recording results

For each section, note pass or fail, the browser used and the window size (1366 x 768 and
1920 x 1080 are the target desktop sizes). For a failure, write down what you did, what you
expected and what happened, plus a screenshot. Report failures in
[bugs and verification](../progress/bugs-and-verification.md).

Scope: private concerns only. Pilot, an AI planner, plans and maps, bookings and payments are
later work.
