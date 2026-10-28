# TripPilot: project context

Everything decided and discovered so far, written to be handed to a person or an AI tool as context.
Last updated 2026-10-23.

## 1. What TripPilot is

**One line:** an AI agent that turns a friend group's messy trip plan into a booking everyone has committed to and paid for, with no one fronting money and no one chasing debts.

TripPilot is an AI co-pilot for group trips. It plans the trip with the group, reprices it every time someone changes their mind, then books and pays for it together through PayPal. Deterministic code calculates every amount; people approve every money move.

**Built for:** the PayPal AI Hackathon (Devpost, online, global). Team of 3. Built and demoed entirely in the PayPal sandbox.

## 2. Hackathon facts that shape the project

| Item | Detail |
|---|---|
| Submission deadline | **Nov 12, 2026, 12:00 PM PT** (3:00 PM ET) |
| Judging | Dec 1–15, 2026; winners around Dec 21, 2026. The hosted demo must stay up until then |
| Requirement | Meaningfully use PayPal (sandbox) **and** AI. Venmo, Braintree etc. count as PayPal |
| Submission | Public GitHub repo with an open-source licence, run instructions or hosted URL, text description, tools used, YouTube video under 3 minutes |
| Judging criteria (equal weight) | Technological implementation, Design, Potential impact, Innovation, Presentation |
| Prize limit | One main prize plus one sponsor prize per project |
| Main prizes targeted | Best Use of Agentic Commerce, Best Use of PayPal + AI, Most Impactful |
| Sponsor tools chosen | Bryntum (itinerary), AG Grid / AG Studio (money dashboard), Render (hosting), APIMatic Context Plugin (building the PayPal integration) |
| Sponsor tools skipped | Zapier, Elastic, KERNEL, Astropods, Channel3 |

## 3. Problem and audience

**Audience:** groups of 5–12 young adults, roughly 20–35, in the US (USD), planning trips with friends from college, school or work. Usually 2–3 people act as lead planners; the rest give feedback, agree and pay.

**Problem:** group trips break in two places.
1. **Planning:** endless group-chat debate about where to go, how much to spend and what to do. Every change means someone redoes the plan and budget by hand.
2. **Money:** one friend pays for the cabin up front and chases everyone for weeks. Someone who can't afford it quietly drops out or ends up owing money awkwardly.

## 4. The user journey

1. **Choose where to go (AI planning).** Planners enter the start city, dates, trip length and up to three per-person budgets (e.g. $250 / $400 / $600). The agent suggests destinations for each budget with live-price estimates for travel, stay, food and activities. Members privately mark which budget they're comfortable with, so nobody has to say "I can't afford it" in front of everyone. The group picks a destination that works for everyone.
2. **The first plan (AI planning).** The agent builds version 1: stays with live nightly prices and room setups for the group, transport there and around, and a day-by-day itinerary with travel times on a drag-and-drop Bryntum calendar. The AI proposes cost lines; code adds them into a per-person budget.
3. **Negotiate until it's locked (AI replanning).** Members ask for changes in plain words, e.g. "drop Z Point" or "I want one chill day". Each change makes a new version showing what changed, who asked and the cost change per person. Planners accept or reject. After a few rounds the plan is locked.
4. **Book and pay together (Group Checkout).** See section 5.
5. **During the trip (trip tab).** Anyone adds an expense, often by snapping the receipt; the AI reads it and suggests a split; the payer confirms. Each member settles now, in part, by a chosen date or at trip end. Anyone owed money is paid back by PayPal payout.
6. **Wrap-up (settle up).** A final settle-up shows a near-minimal set of payments to clear everyone. Refunds go back to whoever actually paid. Each member gets a summary.

## 5. Money design

### 5.1 Group Checkout (core)
For each big booking (stay, rental car, activities):
1. The agent re-checks the live price and proposes the booking.
2. Planners approve it with a price cap and a deadline.
3. Each member **commits their share**, which places a PayPal **authorization hold** on their own account for a capped amount ("up to $230" on a $200 share).
4. A progress bar shows "6 of 8 committed"; the agent sends friendly reminders.
5. When everyone is in, code re-checks the price, **captures** each hold for the final share (the rest of each hold is released), books with the vendor and pays the vendor by **PayPal Payout**. The itinerary item locks as booked.
6. If the deadline passes or the price rises above the caps, every hold is **released (voided)** and nobody is charged.

Details:
- **Drop-outs:** caps cover the remaining members' larger shares without asking again; below that, the group decides (cancel, someone covers, or a cheaper option).
- **Partial participation:** only people doing an activity commit to it.
- **Hold timing:** PayPal guarantees funds for 3 days after authorization; an authorization is valid for 29 days and can be reauthorized (which restarts the 3-day window). Commit windows stay within 3 days.
- **States:** Proposed → Open → Fully committed → Charged and booked; or Released; or Needs a decision.
- **Failure handling:** booking fails after capture → refund everyone automatically; payout fails → retry with the same request ID, then flag a planner.

### 5.2 Cover a friend
A member who can't pay right now privately asks a friend to cover them. The friend commits both shares (one order, two line items); the covered member confirms the terms (amount, due date, repayment plan) before it's final. TripPilot records an agreed, private loan. The group only sees the member as "committed". Repayment through TripPilot (pay-in, then payout to the lender), outside the app (lender marks received), or automatically with saved PayPal. The lender can forgive the rest at any time. If the covered member drops out before booking, that part of the lender's hold is released and no loan is created.

### 5.3 Trip tab and settle-up
Expenses during the trip: payer, amount in whole cents, split method (equal, shares, exact), participants, receipt image. Members settle now, partly, by a date or at trip end. Settle-up uses netting plus greedy matching, described as "near-minimal".

### 5.4 What PayPal can and can't do here
- No public API moves money between two personal accounts (P2P), so all settlement routes through TripPilot's business account: pay-ins by checkout, pay-outs by Payouts.
- In production, TripPilot charging for bookings makes it the seller (merchant of record, like a travel agency). PayPal's merchant terms forbid receiving payments on behalf of others, so a production version would move to PayPal's multiparty platform products. One line in the pitch.

## 6. Guardrails (the money rules)

1. **Code does the maths, not the AI.** Every amount, split and balance is computed deterministically in whole cents.
2. **People approve every money move.** The agent can search, propose and remind freely. Gated tools (open checkout, capture, book, pay vendor, pay out, refund) need a recorded approval and automatic checks: matching unexpired approval, quote within cap, everyone committed, unique request ID.
3. **No surprise debt.** Nobody can create a debt for someone else without that person agreeing.
4. **Everything is traceable.** Each step, approval and PayPal ID is logged and shown in an "Agent activity" panel.

### Proposed refinements from research (status: proposed, for team discussion)
| # | Change | Source |
|---|---|---|
| D1 | Approval cards are drawn only by code from the vendor quote; AI text explains but never sets amount or payee | Aviv et al. 2026, security analysis of Google AP2 |
| D2 | Each commitment is a mandate: trip, cap, payee, expiry, one checkout only, one-time code, request ID on every call | Google AP2 spec; OpenAI/Stripe ACP payment spec; Li et al. 2026 (x402 attacks) |
| D3 | Money tools can't be reached from untrusted text (listings, vendor messages, chat) | Debenedetti et al. 2025, CaMeL |
| D4 | Early-bird perk for members who commit early if a checkout fails | Cason et al. 2026, refund bonuses |
| D5 | Organiser coordinates but can't move others' money; members see only what concerns them | Lee & Bellini, CHI 2025 |
| D6 | Automatic checks: total charged ≤ sum of caps; holds only move through allowed states | Jiang et al. 2026, formal analysis of agent payment protocols |
| D7 | Capture only after the vendor confirms price and availability; append-only ledger | Goenka et al. 2026, TessPay |
| D8 | Settle-up is "near-minimal" (netting + greedy) | Bultel et al. 2020 |
| D9 | In agent-to-agent negotiation, the hold is the hard budget and code ranks offers | Zhu et al. 2025; Magentic Marketplace 2025 |
| D10 | Plain-language limits become a scope the member confirms | South et al. 2025, authenticated delegation |

## 7. Positioning and honest novelty

- **Not novel as a mechanism.** Group split payments at checkout exist: Airbnb's split payments (from its 2017 Tilt acquisition, retired in 2018), Hands In, FairShare, Tab, PayByGroup (2012). "Charge only if everyone's in" is an assurance contract (the Kickstarter model). Airbnb dropping the feature is evidence groups found it more hassle than one person paying.
- **Distinctive as an agent-driven flow.** No existing product combines: an agent that finds the option, opens the checkout, chases, re-splits on drop-outs, re-checks price, captures and pays the vendor; money tied to a negotiated plan (every change reprices and re-splits); capped automatic re-splits; Cover a friend inside the commitment; any vendor via payouts.
- **Pitch framing:** lead with the plan → reprice → commit loop. Group Checkout is the payoff, not the headline. Name Airbnb's split payments directly and say what's different.
- **Honest scores:** mechanism 2/5; agent-run group commitment tied to the plan 3.5/5; hackathon fit 4/5; real business 2/5 for now.
- **Competitors in planning + splitting:** Splitwise, Venmo Groups, Stamp'd, WaySide, PlanIt, Wanderlog. Past PayPal hackathon winners include SplitIt (debts between friends) and Ajo (group contributions), so judges have seen splitting apps.

## 8. Architecture

**Components**
- **Web app (React + Vite):** trip screens, approval cards, commitment progress, PayPal JS SDK v6 buttons, Bryntum itinerary, AG Grid money board, agent activity panel.
- **Backend (Python FastAPI):** trips, members, plan versions, ledger, Group Checkout logic, gated money tools and checks, webhook handling.
- **Agent worker:** runs Claude with tools (destination search, plan building, replanning, proposals, reminders, receipt reading). Event-driven: woken by user actions, PayPal webhooks and timers via a Postgres job queue (`FOR UPDATE SKIP LOCKED`). Each run is short: read state, call Claude with a step and time limit, save and log, stop. Waiting is a scheduled job.
- **Postgres:** source of truth for trip state and the job queue. The agent reads state fresh each step.
- **Mock vendors:** two small services (e.g. "Cedar Lake Cabins", "Lakeside Kayak Rentals") with quote and booking endpoints, real-listing prices and their own sandbox PayPal business accounts.
- **Live data:** Google Hotels via SerpApi (stays), Duffel (flights), Google Places and Routes (attractions, travel times). Cached with a "price checked at" time. Amadeus self-service APIs were shut down in July 2026.

**Data model (entities):** Trip, Member, PlanVersion, PlanItem, Approval, GroupCheckout, Commitment, Expense, Loan, Settlement, AgentEvent.

**PayPal capabilities used:** Orders v2 with authorize intent (holds), capture / void / reauthorize, Payouts, Refunds (Payments v2), Payment Method Tokens (saved PayPal, US only), Webhooks, Agent Toolkit or MCP for agent questions.

**AI:** Claude API with tool use (Opus 5.5 for planning and replanning, Haiku 5.5 for quick tasks like reminders and receipt reading). Proposed, not final.

**Hosting (Render, ~$20/month, inside $50 credits):** Starter web service (app, webhooks, mock vendors as routes), Starter background worker, Basic Postgres. Free tiers are unusable (web services sleep after 15 minutes; free Postgres is deleted after 30 days).

**Keeping the demo alive until Dec 21:** nightly "Reset demo" that rebuilds the sample trip with fresh holds (holds expire after 29 days); simulated friends with saved PayPal so their commitments are real holds placed automatically; judge mode with personas; spending limits on Claude and cached sample plans; uptime monitor; daily end-to-end sandbox test; tagged submission release; `docker compose` fallback; Bryntum and AG Grid 45-day trials activated around Nov 1.

## 9. Stage 1 sandbox findings (verified 2026-10-22)

| Check | Result |
|---|---|
| PayPal hold → capture $0.50 of $1.00 with `final_capture` → rest released (authorization ends `CAPTURED`) | ✅ Works |
| PayPal hold → void (`VOIDED`) | ✅ Works |
| PayPal pay now (capture `COMPLETED`) | ✅ Works |
| Payout to a member (sandbox personal account) | ✅ Works, no activation needed in sandbox |
| Payout to a vendor (second sandbox business account) | ✅ Works |
| Saved PayPal: buyer approves once, then a $1.00 hold with no login, then void | ✅ Works. With a saved PayPal, create-order returns `COMPLETED` with the authorization already placed |
| Venmo payouts | ❌ "Recipient wallet not supported in sandbox" |
| Venmo checkout | ❌ Button shows, but the Venmo login rejects sandbox accounts and Venmo test accounts can't be self-created. Venmo is roadmap-only unless PayPal provides a login |

**Lessons learned:**
- PayPal reuses an access token until it expires (~9 h), and permissions are fixed at issue. After changing app features in the dashboard, revoke the token (`POST /v1/oauth2/token/terminate`) and request a new one. The real backend needs this too.
- Saving PayPal needs both "Save payment methods" and "PayPal and Venmo" enabled on the sandbox app.
- The hosted PayPal MCP (`mcp.sandbox.paypal.com/mcp`) has only 10 tools (invoices, payment links, transactions, disputes) and no orders, captures or refunds, so the app calls the REST API directly.

**Still to check:** several members' holds in one checkout run; saved PayPal for several sandbox buyers; webhooks arriving on Render; renewing a hold after the 3-day honor period.

**Next planned test (not built yet):** 3 members with saved PayPal, $6.00 booking, $3.00 caps. Scenarios: everyone in; one drop-out (re-split to $3.00 × 2); price rise to $10.00 past the caps (code refuses to charge and releases all holds); retry with the same request ID (no double charge). Share maths as a pure function with pytest tests (whole cents, deterministic leftover cents).

## 10. Scope (3 people, ~3 weeks)

| In | Stretch (only if "In" works by Nov 4) | Out |
|---|---|---|
| One region with live prices | Saved PayPal auto-settling for every member | Many destinations |
| Planners accept or reject changes | Pay Later messaging | Full group voting |
| Group Checkout, Cover a friend, trip tab, payouts, refunds | **Agent-to-agent rate negotiation (first stretch goal)** | Real booking partners |
| Two mock vendors | Duffel test-mode booking | Zapier, Elastic, KERNEL, Astropods, Channel3 |
| Approvals and activity panel | | |
| Bryntum, AG Grid, Render, APIMatic | | |

## 11. Development stages

| Stage | Dates | Done when |
|---|---|---|
| 0 · Setup | Oct 22–23 | App live on Render, CI green, sandbox accounts listed |
| 1 · Prove the risky parts | Oct 23–27 | Holds, payouts, saved PayPal, webhooks, live prices and agent loop proven; go/no-go recorded |
| 2 · Foundations | Oct 26–Nov 1 | Ledger tests pass, job queue runs, PayPal client reusable |
| 3 · Planning agent | Oct 29–Nov 4 | New trip reaches a locked plan with live prices |
| 4 · Group Checkout and booking | Oct 31–Nov 6 | 8 members book the cabin in sandbox, including one cover and one drop-out |
| 5 · Trip tab and settle-up | Nov 4–8 | Demo trip closes with every balance at zero |
| 6 · Demo hardening | Nov 7–10 | A teammate runs the demo from the README without help |
| 7 · Submit | Nov 10–12 | Submitted by the evening of Nov 11 |
| 8 · Keep it running | Nov 12–Dec 21 | Site up and daily sandbox test green until winners |

Feature freeze Nov 9. Roles (proposed): frontend; backend and payments; AI and data.

## 12. Demo script (under 3 minutes)
1. The problem: one friend fronts $1,600 and chases seven people.
2. Three budgets lead to a destination the whole group can afford.
3. AI drafts the plan with live prices in Bryntum.
4. "Drop Z Point" and "add a chill day": replan with cost change; plan locked.
5. Cabin Group Checkout: progress bar fills, one friend covers another, last commit books it automatically, activity panel shows each step.
6. Receipt photo becomes a split expense; AG Grid board updates.
7. Settle-up: payouts go out, one person defers to Friday, trip closes.

State clearly in the video: real prices, sandbox bookings and payments.

## 13. Risks
- Bryntum and AG Grid trials expiring during judging → activate around Nov 1, confirm on the PayPal Discord.
- Demo holds expiring (29 days) → nightly reset.
- Judges running up AI or price-search costs → spending limits, per-visitor limits, caches.
- Mock vendors can make the payment step look staged → real prices, say it plainly.
- Airbnb's retired split payments → address it directly in the pitch.
- Production merchant-of-record and multiparty requirements → one line in the pitch.
- Scope creep → stretch items only after the week-2 end-to-end flow works.

## 14. Decisions so far
- Market: US, USD. Venmo is roadmap-only.
- Core money design: Group Checkout with capped holds, plus Cover a friend, trip tab and payouts. The trip-wallet pool is not the core.
- Live prices, not AI estimates.
- First stretch goal: agent-to-agent negotiation.
- Roles: not yet assigned.

## 15. Current project setup
- Folder: `C:\NEU\Projects\Trip pilot` (git repo).
- Python 3.12 with a uv-managed `.venv`; dev tools ruff (single quotes), mypy (strict), pytest.
- `.env` holds sandbox credentials (git-ignored); `.env.example` is the template.
- `venmo_sandbox_test.py`: sandbox test script (payouts, Venmo and PayPal checkout tests, saved PayPal, token renewal, report).
- `docs/design-notes.md`: proposed design changes and Stage 1 findings, for team discussion.
- Proposal page with diagrams and stage cards: https://claude.ai/artifact/GTmaiK2L4fX9yqkYcUUDfa
