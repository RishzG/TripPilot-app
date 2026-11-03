# TripPilot planning archive

Saved November 3, 2026 (America/Chicago). This archive preserves the discussion so it can be continued without relying on chat history. It is a working specification, not a finalized implementation contract.

- [Product discussion and decisions](discussion-and-decisions.md): intended journey, alternatives, feature tradeoffs, sponsor options, costs, unresolved questions, and editable Mermaid diagrams.
- [Milestone 01: planning, replanning, and payment feasibility](milestone-01.md): concrete scenarios, architecture, proposed interfaces, acceptance checks, and implementation order.
- [Payment feasibility evidence](payment-feasibility.md): official documentation findings, missing execution prerequisites, smallest valid sandbox proof, and a support question draft that has not been sent.
- [UI concepts](ui-concepts.md): nine active desktop concept images covering the discussed features, an archived future mobile concept, and behavior notes.

Editable chart sources are also saved separately: [app journey](diagrams/app-journey.mmd), [system architecture](diagrams/system-architecture.mmd), and [planning/replanning sequence](diagrams/planning-replanning-sequence.mmd). The Markdown documents embed the same Mermaid diagrams for preview in compatible viewers. Ten selected PNG concepts (nine desktop, one archived mobile board) are stored locally under `images/`, along with an unselected expense-screen draft; [original image prompts](image-prompts.md) and [additional desktop prompts](desktop-feature-prompts.md) record how they were generated.

## Which source wins?

1. The user's direct descriptions and explicit answers in this conversation.
2. Explicitly accepted decisions in these documents.
3. Technical recommendations, still subject to discussion and implementation evidence.
4. Teammates' earlier documents as historical alternatives, not instructions.

## Repository distinction

This archive is saved in `D:/Projects/TripPilot`, whose Git remote is `https://github.com/shash3n/TripPilot.git`. That checkout contains starter application code and existing uncommitted changes.

The more developed project described by the update PDF is `https://github.com/RishzG/TripPilot-app`. Its source was inspected read-only through the GitHub connector. Do not assume that its application modules exist in this checkout. No repositories were merged, no remote files were changed, and this archive has not been pushed.

## Continuation handoff

The next agreed topic is a complete planning-and-replanning slice alongside a payment feasibility proof. The current request authorizes saving documentation and continuing milestone planning; do not silently replace the user's member-to-leader payment flow with the older authorization-hold or agency flow. Confirm the implementation checkout before changing application code.

The payment design remains unresolved. The user explicitly wants discussion before any fallback is selected.

Latest explicit direction: **continue technical design only for now**. Do not begin application implementation or create an implementation checkout from this archive alone. Explicit rejection offers discussion with the leader or opt-out; opt-out triggers recalculation and fresh acceptance. For non-refundable costs, the leader proposes a case-by-case arrangement for affected members to accept. Individual payment approval remains required. The next discussion should settle the sample scenario and supported payment verification path.

Demo platform is **desktop web only**. Mobile implementation, phone-browser testing, and touch-specific polish are outside the demo scope. Retain the mobile concept image for historical context rather than deleting it.
