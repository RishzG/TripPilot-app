# Payment feasibility: evidence log

Checked November 3, 2026. Status: documentation research complete for the initial pass; intended sandbox transfer not executed. This file is a feasibility record, not a claim that the payment flow is supported or unsupported under every possible PayPal partnership.

## Required product behavior

US members using USD explicitly contribute from their own PayPal accounts to the trip leader's personal PayPal account. TripPilot independently verifies the transfer and updates contribution progress. The leader later completes external merchant checkout. Internal reimbursement/settlement should follow the same supported payment principles.

The user wants verified sandbox transfers investigated first and requires discussion before any fallback. No agency, business-account proxy, platform custody, or authorization-hold replacement has been accepted.

## Findings

| ID | Evidence | Implication | Verification level |
| --- | --- | --- | --- |
| P-01 | PayPal login grants consented identity claims | It does not itself establish payment execution or account-wide transaction-history permission | Official identity documentation reviewed |
| P-02 | Webhook subscriptions receive only events associated with their specific app | Adding a TripPilot webhook does not make unrelated personal payments visible to that app | Official webhooks overview reviewed November 3 |
| P-03 | Transaction Search's published specification requires partner-network access for third-party accounts | Reading a leader's history cannot be assumed available from ordinary app credentials | Official OpenAPI specification reviewed November 3 |
| P-04 | REST credential setup associates an app with a sandbox business account | A successful merchant sandbox test would not prove the user's intended personal-to-personal flow | Official credential setup instructions reviewed November 3 |
| P-05 | PayPal.Me supports requests/contributions between friends | User-facing payment initiation exists, but automatic TripPilot verification and intended sandbox support remain unproven | Official product/help pages reviewed during discussion |
| P-06 | Teammate code/report covers vaulted holds, captures, voids, and business payouts | Useful reusable integration infrastructure, not proof of the revised account-to-account flow | Source/report inspection, no new live execution |
| P-07 | Local dotenv contains only a database setting; no PayPal application credentials were found in relevant process settings | Cannot execute a sandbox transfer from this checkout with currently available configuration | Setting names only inspected; no secret values printed |

## Initial verdict

**The requested automatic verification is not yet demonstrated.** The main obstacle is identifying a supported authorization and verification path for payments received by a personal-account leader. Ordinary login plus ordinary app webhooks is not sufficient evidence.

The documentation does not establish a generally available solution for this team's intended account types and permissions. Do not turn this limited finding into an absolute claim that no partner-specific integration could exist.

## Smallest valid proof

1. Identify the supported API/product and required permissions for the exact account model, with official documentation or a written response from PayPal's hackathon support team.
2. Configure one sender and one intended leader recipient in sandbox. Keep all secrets outside the documentation and repository.
3. Initiate a small USD transfer with explicit sender approval through the supported mechanism.
4. Independently obtain final status, recipient, amount/currency, and a stable reference server-side. Do not trust a browser success URL, uploaded receipt, or fabricated webhook as proof.
5. Re-submit/replay once; contribution totals must remain unchanged after the first confirmed recording.
6. Check cancelled approval, incorrect amount/recipient, delayed completion, and reversal behavior.
7. Record sanitized transaction references and outcomes. Only mark this supported after execution succeeds with the intended account model.

Provider credentials alone do not resolve permissions or account-type limitations. Do not ask members for their PayPal passwords or API secrets. If support is access-gated or unavailable, discuss the product alternatives before implementing a different money route.

## Questions prepared for PayPal support (not sent)

> We are building TripPilot for the hackathon: a US/USD friend group contributes personal funds to a personal-account group leader, who then books externally. We need explicit user-approved transfers and server-side confirmation of recipient, amount, currency, and final status. Is there a supported sandbox/API integration for this exact personal-account flow? If so, which API, consent/scopes, account eligibility, and webhook/reporting path should we use? Does verification require partner onboarding, and is that available within the hackathon? We are not treating merchant Orders or business-funded Payouts as equivalent to personal P2P.

No messages have been sent to PayPal or teammates. The draft is available for the user to review/send or to explicitly authorize sending through a connected channel.

## Official evidence links

- Login identity: https://developer.paypal.com/log-in/how-it-works/
- Webhook app scoping: https://developer.paypal.com/api/rest/webhooks/
- Transaction Search OpenAPI: https://github.com/paypal/paypal-rest-api-specifications/blob/main/openapi/reporting_transactions_v1.json
- REST credential setup: https://securepayments.paypal.com/us/cshelp/article/how-do-i-create-paypal-rest-api-credentials-ts1949
- Sandbox accounts / REST getting started: https://developer.paypal.com/api/get-started/
- PayPal.Me product: https://securepayments.paypal.com/paypalme/
- Hackathon resources/support entry point: https://paypalaihackathon.devpost.com/resources

## Decision record

| Decision | Current state |
| --- | --- |
| Intended personal-account verified transfer | Preferred; not yet proven |
| Personal payment links + recipient confirmation | Not selected |
| Sandbox business-account checkout demonstration | Not selected |
| Business-funded platform payouts / custody | Not selected |
| Capped authorization holds from earlier proposal | Superseded product direction; not selected as fallback |
