# OpenMCP MVP implementation tickets

Approved for implementation, October 3, 2026. Work is assigned to two implementation agents and a coordinating agent. Tickets describe required behavior, not a claim of completion.

OpenMCP will let a person sign in, load a prepaid USD balance, authorize an LLM to spend a limited amount, and inspect the services it bought. The LLM discovers registered services, purchases one, and receives its result. A terminal purchase failure returns the user's credits. This document defines the product, the frontend and backend deliverables, their shared contract, and the acceptance tests for this iteration.

The user has confirmed that payments must support real money and that “get money back” means service results plus failure refunds. Withdrawals are not requested. The user approved execution of the scoped plan, including the prepaid-credit model, platform settlement wallet, fee policy, and detailed scope below.

**The product being built**

The customer is a person using an MCP-compatible LLM client. Their website has three main views: Overview, Transactions, and Agents. Clerk supplies sign-in, sign-up, and profile controls. Stripe supplies the payment form. OpenMCP supplies the balance, spending authority, service catalog, purchases, and transaction history.

The backend is a FastAPI application with PostgreSQL and one durable worker. It authenticates both people and agents, records credits and spending reservations, processes Stripe events, discovers services, and settles provider requests through MPP. A local stdio MCP client connects an LLM to that account-backed API using a scoped credential.

The primary acceptance journey is concrete:

1. A new user signs in and sees a zero balance.
2. They add $10 through Stripe Checkout with Link available.
3. After verified payment, their available OpenMCP balance becomes $10.
4. They create an agent with a $2 total spending allowance and connect their LLM.
5. The LLM discovers a service priced at $0.40 and buys it.
6. While processing, the wallet shows $9.60 available and $0.40 pending. The agent has $1.60 available allowance.
7. On success, pending becomes zero, $9.60 remains available, and the LLM receives the service result and provider receipt.
8. On terminal failure, the reservation is returned once, restoring the wallet to $10 and the agent allowance to $2. The failed attempt remains visible.

**Money and authorization rules**

- The customer wallet is a prepaid USD credit ledger. It is not a crypto address. Stripe collects funds for OpenMCP; a confirmed top-up creates credits for the authenticated account.
- The platform separately funds a mainnet stablecoin wallet to pay providers. Automatic conversion or transfer of Stripe proceeds into that wallet is outside this iteration. Low settlement liquidity must block new purchases before signing a payment.
- The account purchase path charges the user's credit balance and makes one outgoing MPP payment. It must not additionally charge the old local agent crypto wallet.
- Retain the existing proposed 10% platform margin within the advertised retail price. A $0.40 service pays $0.36 to its provider. The retail price is the user's complete service charge; the platform absorbs network fees. A $10 top-up creates $10 of credits, with processing costs absorbed by the platform for this iteration.
- Each agent has an owner-authorized lifetime spending cap, with no automatic reset. Reservations consume its available allowance; successful purchases consume spent allowance; failed purchases release allowance. Top-ups and replacement credentials do not reset or increase that cap. A user creates a new grant to authorize additional spending in this MVP.
- All credentials for an agent share its cap. Concurrent agents still share the account's available balance. Agents cannot fund accounts, create grants, change caps, or request discretionary refunds.
- The LLM also follows the user's task budget in the purchasing skill. The hard backend authorization boundary is the owner-issued agent cap. For an exact per-task hard cap, the user creates a grant for that task. A model-supplied budget is never treated as new spending authority.
- Confirmed payment and result delivery are distinct. Unknown payment outcomes retain the reservation while reconciled. A timeout alone does not establish that no payment occurred.
- A confirmed terminal fulfillment failure returns the full retail amount to the customer. If the provider was already paid, the platform records that cost separately and absorbs it. Refunds never imply reversal of an on-chain payment.
- Funding reversals and disputes require separate accounting from service refunds. They can restrict the account and create a recorded deficit; an implementation must not hide that deficit by clamping the ledger to zero.

**Scope boundary**

Included: personal accounts, USD only, real-money configuration, Clerk authentication, Stripe Checkout and Link, credit funding, transaction history, capped agent credentials, curated service discovery, MPP purchasing, failure refunds, durable recovery, and the MCP purchasing skill and connection instructions.

Excluded: cash withdrawals, peer transfers, organizations, recurring billing, automatic treasury funding, general exchange-rate support, provider self-service onboarding, Stripe Connect payouts, x402, arbitrary URL purchases, API Creator expansion, a new standalone SDK product, native remote MCP/OAuth hosting, and an operator web dashboard. Existing provider SDK code is reused and adapted where necessary. Operational reconciliation is a restricted CLI workflow.

At the start of this iteration, the repository had a Next.js frontend, a local stdio MCP server, a testnet MPP engine, provider SDK, and account/credit foundations. Those accounts were not connected to the purchasing engine. The old product ledger loaded and rewrote a shared snapshot; this iteration adds incremental transactional writes in an isolated account runtime. The testnet catalog and Creator registrations are not automatically authorized for live payments.

**Frontend experience and states**

| Surface | What the user sees and can do | Required states |
| --- | --- | --- |
| Public home | Understand the product; sign in or open their dashboard | Signed out, signed in |
| Sign in and sign up | Clerk authentication and return to the intended protected page | Loading, success, error |
| Overview | Available balance, pending amount, total successful service spend, recent activity; add money or connect an agent | First use, funded, purchasing, refund, restricted account, connection failure |
| Add money dialog | Custom amounts from $1 to $50; $5, $10, $25, $50 suggestions; continue to Stripe | Idle, creating checkout, redirect, recoverable error |
| Top-up return | Actual status of this payment and its wallet credit | Waiting for confirmation, credited, failed, expired; cancellation is displayed without asserting payment failed |
| Transactions | Filterable chronological deposits, purchases, service refunds, and funding reversals | Empty, loading, pagination, filtered empty, error |
| Transaction detail | Amount, state, time, service/agent, linked refund or original transaction, applicable receipt | Completed, processing, failed, under review, refunded |
| Agents | Create an agent with name, cap, expiry; view spent/pending/remaining; revoke credentials; connect an LLM | No agents, active, exhausted, expired, revoked |

Preserve the existing typography and restrained lavender/neutral visual language. Use a compact sidebar or mobile navigation for Overview, Transactions, and Agents. Prefer balance cards, explanatory empty states, and a readable transaction table over charts for this iteration. Public copy must describe the funded account flow accurately.

**Shared API contract**

Human requests use verified Clerk sessions. Machine requests use hashed OpenMCP agent credentials. Stripe webhooks use their own signature verification. An API accepting both human and machine authentication still applies each principal's specific permissions. Agent history and execution reads are limited to its own executions; the owner can see the whole account.

All monetary fields are integer cents; timestamps are UTC ISO 8601. Paginated endpoints return `items` and `next_cursor`, with a bounded `limit`. Errors retain the existing `error.code`, `error.message`, and `error.retryable` envelope and add `request_id`. Unknown or unowned resource IDs return 404. Private responses are not shared-cacheable.

| Method and route | Principal | Request or purpose | Successful response |
| --- | --- | --- | --- |
| `POST /v1/me/bootstrap` | Human | Provision by verified Clerk subject; no caller account ID | Account ID and account status; repeat returns same account |
| `GET /v1/me` | Human | Account and public application configuration | Account status, currency, top-up presets, operating mode |
| `GET /v1/wallet` | Human or agent | Read spendable funds | Balance, reserved, available, deficit, currency; agent response also includes cap/spent/reserved/remaining |
| `POST /v1/wallet/top-ups` | Human | `amount_cents`; `Idempotency-Key` header | Top-up ID, checkout URL, expiry, status |
| `GET /v1/wallet/top-ups/{id}` | Owning human | Read/reconcile provider-verified top-up state | Amount, payment status, credited timestamp if any |
| `POST /v1/webhooks/stripe` | Stripe signature | Raw signed event | Acknowledgment after durable event acceptance |
| `GET /v1/transactions` | Human | Cursor, limit, type/status filters | Account transaction summaries |
| `GET /v1/transactions/{id}` | Owning human | Transaction details | Safe receipt, linked transaction/execution, amounts and status |
| `GET /v1/agents` | Human | List grants and credential metadata | Names, caps, usage, expiry, credential IDs/status; no secrets |
| `POST /v1/agents` | Human | Name, positive `spend_limit_cents`, expiry | Agent ID and grant terms |
| `POST /v1/agents/{id}/credentials` | Owning human | Issue credential within grant lifetime | Credential ID and secret shown once |
| `POST /v1/agents/{id}/credentials/{credential_id}/revoke` | Owning human | Revoke one credential | Revoked status; repeat is harmless |
| `POST /v1/discover` | Agent | Query and optional requested affordability limit | Matching service IDs, descriptions, schemas, retail prices, affordability |
| `POST /v1/execute` | Agent | Endpoint ID, payload, `max_price_cents`; `Idempotency-Key` header | 200 completed execution or 202 pending execution with status URL |
| `GET /v1/executions/{id}` | Owning human or originating agent | Read completion or reconciliation outcome | Execution status, result when completed, charged/refunded amounts, safe provider receipt |

The account flow does not accept the demo's global `session_id`, reset behavior, or a caller-provided total budget as authorization. Exact payload schemas and error codes are frozen in INT-01 before either agent implements integrations. The public credit mutation routes must not remain available to create arbitrary credits or arbitrary unlinked debits.

Canonical top-up states: `creating`, `awaiting_payment`, `processing`, `credited`, `failed`, `expired`. A return-page cancellation is a navigation event; the backend checks whether the payment actually succeeded. Later funding reversals are separate ledger transactions, not deletion of the credited deposit.

Canonical execution states: `reserved`, `payment_pending`, `fulfillment_pending`, `completed`, `failed`, `refunded`, `needs_review`. `failed` is terminal before any reservation/charge; `refunded` means reserved or charged credits have been returned. `needs_review` retains any unresolved reservation and exposes a useful status message. Payment status, fulfillment status, and customer accounting are stored separately even when the UI shows one summary label.

**Frontend tickets for agent 1**

**FE-01 — Add Clerk authentication and the account shell**

Priority: P0. Depends on INT-01; API integration depends on BE-01.

User outcome: a person can sign in and return to their own dashboard.

Action items:

- Follow `frontend/AGENTS.md` and the installed Next.js version's documentation. Run Clerk setup from `frontend/`, inspect its changes, and use the current SDK and route conventions.
- Add sign-in, sign-up, profile/sign-out controls, and protection for `/dashboard` and its nested routes.
- Build the shared navigation and responsive account layout. Update landing-page calls to action to enter this flow.
- Bootstrap the OpenMCP account after authentication and handle first-use, loading, unauthorized, and backend-unavailable states.
- Add a narrow same-origin API layer that obtains and forwards the Clerk session token to the configured backend, checks origins on browser mutations, and never forwards the demo operator token. Disable shared caching of account responses.

Acceptance: signing in twice maps to the same account; unauthenticated dashboard access reaches sign-in and returns correctly; signing out removes private content; one user's rendered data is never reused for another. Run Clerk diagnostics and verify controls in the browser. Keep secrets out of rendered HTML, logs, and version control.

The [Clerk setup skill](https://clerk.com/SKILL.md) asks for review before changing existing authentication. The proposed migration adds human authentication and maps Clerk subjects to the existing account domain; it retains scoped machine credentials and does not import demo account balances into real-money accounts.

**FE-02 — Build the wallet overview**

Priority: P0. Depends on FE-01, BE-02, and BE-07.

User outcome: a person understands what they can spend and what is pending.

Action items:

- Show available funds prominently, pending reservations separately, and successful service spend without counting refunded purchases twice.
- Add recent activity with links to transaction detail, Add money, and Connect an agent.
- Provide a first-use checklist: fund balance, create agent, connect client. Do not require a payment before allowing free discovery.
- Refresh after return from Checkout and when pending purchases change; use bounded polling with backoff and stale-data/error states.
- Display restricted-account and insufficient-balance explanations supplied by the API. Distinguish customer USD credits from provider settlement tokens.

Acceptance: the $10 / $0.40 example above renders correctly during reservation, completion, and refund; reload preserves the server truth; an API failure never appears as a zero balance; loading and small-screen layouts remain readable.

**FE-03 — Implement top-up and return flows**

Priority: P0. Depends on FE-01, BE-03, and BE-04.

User outcome: a person funds the correct wallet through Stripe Checkout and can tell when funds are usable.

Action items:

- Accept custom amounts from $1 to $50, offer backend-configured $5/$10/$25/$50 suggestions, and show the amount of credit the user will receive.
- Generate one idempotency key per intended checkout and preserve it through network retries. Disable repeated submissions while a request is unresolved.
- Redirect to the backend-supplied Stripe Checkout URL. Keep card collection within Stripe.
- Implement `/dashboard/top-up/return` using an account-owned top-up ID and actual server status. Do not trust a success query parameter as evidence of payment.
- Show processing, success, cancellation, expiry, and recoverable errors. Persist a route back to the dashboard if the user closes the return page.

Acceptance: repeated clicks/retries reuse one top-up; an unpaid or tampered return URL never adds credits; delayed confirmation eventually updates the balance; returning under a different account cannot reveal the payment. Link is available when enabled for the Stripe account, as described in [Stripe's Checkout documentation](https://docs.stripe.com/payments/link/checkout-link).

**FE-04 — Build transaction history and detail**

Priority: P0. Depends on FE-01 and BE-07.

User outcome: a person can explain every change to their wallet.

Action items:

- Add cursor-based pagination and type/status filters with useful empty/error states.
- Show date, description/service, agent where relevant, amount, and state. Use clear labels for money added, pending purchases, completed purchases, refunds, and funding reversals.
- Add a detail drawer or page with transaction ID, amount, linked original/refund record, status explanation, and permitted receipt link.
- Link a purchase to its execution result; show a safe preview/download for supported JSON results. Render provider text as data, not executable markup.
- Preserve selected filters when returning from detail. Label that displayed times are in the user's local timezone.

Acceptance: a returned reservation is not counted as revenue or successful spend; original purchases and refunds remain linked; pagination has no duplicates for a stable cursor; neither raw payment credentials nor other users' results appear.

**FE-05 — Build agent authorization and connection setup**

Priority: P0. Depends on FE-01, BE-08, and INT-02.

User outcome: a person gives an LLM a specific amount of spending authority and can revoke it.

Action items:

- Create an agent with a name, positive lifetime spending cap, and expiry. Explain that the cap limits authority while the account balance supplies funds.
- Show spent, pending, remaining, credential status, and expiry. Explain that a new top-up or replacement credential does not reset the cap.
- Show a newly issued secret once, with copy feedback and guidance to save it privately. Do not place secrets in URLs, analytics, localStorage, or saved connection examples.
- Provide tested MCP setup instructions for the existing supported clients with a secret placeholder and the account-mode runtime command.
- Support credential replacement and revocation. Exhausted grants require a new explicit authorization; there is no automatic cap increase.

Acceptance: a user can create, connect, and revoke an agent; a secret cannot be read back after dismissal; instructions establish a real connection; the UI shows exhaustion distinctly from an empty wallet.

**FE-06 — Verify the complete customer experience**

Priority: P0. Depends on FE-01 through FE-05 and functioning backend contracts.

Action items:

- Add meaningful integration/UI checks for unauthenticated access, bootstrap, top-up state transitions, history, one-time credential display, and API errors.
- Inspect desktop and mobile layouts, keyboard navigation, dialog focus, labels, contrast, and non-color status indicators.
- Run frontend tests, TypeScript checks, production build, and Clerk diagnostics. Ensure production pages make no accidental calls to the local demo runner.

Acceptance: a fresh user can follow the primary journey without developer intervention in the UI; failures explain what happened and which action is safe to retry. External configuration still required for live verification is reported explicitly.

**Backend tickets for agent 2**

**BE-01 — Connect Clerk identities to accounts and define authentication boundaries**

Priority: P0. Depends on INT-01.

Action items:

- Verify Clerk session signatures, trusted issuer, expiry, and permitted parties using the supported backend integration. Read identity from verified claims, not request account IDs or unsigned headers.
- Add a unique Clerk issuer/subject mapping to accounts and idempotent account provisioning. Keep the existing hashed credential mechanism for machines, with distinct principal types and route permissions.
- Implement `/v1/me/bootstrap` and `/v1/me`; add account state such as active/restricted.
- Restrict live account routes from the shared demo token. Disable public demo/reset/operator surfaces in the live application profile and isolate their databases and secrets.
- Document migration of existing account tables. Existing demo/test data must not become spendable live credit.

Acceptance: concurrent first requests create one account; expired/wrong-issuer tokens fail; supplied account IDs cannot switch ownership; a demo token cannot fund or spend live credits; agents cannot call owner-only operations. Authentication behavior follows [Clerk's verification guidance](https://clerk.com/docs/guides/sessions/manual-jwt-verification).

**BE-02 — Implement durable wallet accounting and atomic reservations**

Priority: P0. Depends on INT-01 and BE-01 schema agreement.

Action items:

- Add incremental PostgreSQL persistence for wallet accounts, immutable monetary entries, reservations, and related agent counters. Require Postgres for live mode; keep in-memory adapters only for isolated tests.
- Implement internal operations for verified deposits, reserve, capture, release/refund, and funding reversal. Replace public arbitrary deposit/debit mutations in the account product.
- Atomically check account state, spendable funds, agent expiry/revocation, and agent remaining allowance before reserving. Lock/update the affected records in a consistent order; do not hold SQL transactions open during provider/Stripe calls.
- Store an idempotency fingerprint including account, agent, endpoint, payload, and approved maximum. Reject changed input under the same key. Keep enough durable results to answer a replay after a lost response.
- Return balance, reserved, available, deficit, and agent allowance fields. Preserve the ledger even when a funding reversal creates debt; block additional spending in that case.

Acceptance: two concurrent $0.60 purchases with only $1 available cannot both reserve; capture/release/retry never creates money; repeated deposits/refunds have one monetary effect; replacing a credential does not reset spend. Run these checks against real Postgres, not only an in-memory double.

**BE-03 — Create account-bound Stripe Checkout sessions**

Priority: P0. Depends on BE-01 and BE-02.

Action items:

- Add the Stripe server integration and explicit test/live configuration. Store secret keys server-side and never log raw provider errors containing secrets.
- Implement top-up creation with server-validated presets, USD currency, amount, account binding, and a durable top-up ID. Map or create a Stripe customer for the account.
- Create a hosted Checkout Session with Link/card support, a stable provider idempotency key, and server-owned success/cancel origins. Disable user-controlled redirects and amount-changing checkout options.
- Recover from a lost Stripe create-session response without opening a new payment attempt. Persist session/payment references and return the Checkout URL and expiry.
- Implement account-owned top-up status retrieval and provider reconciliation using the same idempotent credit-posting operation used by webhooks.

Acceptance: changing amount/currency/account in a request cannot bypass validation; repeated requests reuse the same intended top-up; one user's session cannot be retrieved by another; a Stripe outage leaves a recoverable record and no credit.

**BE-04 — Process Stripe payment, reversal, and dispute events**

Priority: P0. Depends on BE-02 and BE-03.

Action items:

- Verify signatures on the unmodified request body, persist accepted events before acknowledgment, and deduplicate Stripe event IDs. A worker processes events with retryable durable state.
- Reconcile server-created Checkout Sessions and credit only verified successful payments with matching amount, currency, account, and live/test mode. Deduplicate the payment itself as well as event delivery.
- Handle delayed success/failure, expiration, duplicate events, out-of-order events, and return-page reconciliation races. Never let a later stale event erase a previously verified payment.
- Handle Stripe-side partial/full refund adjustments and dispute fund withdrawal/reinstatement idempotently. Record the actual monetary change and account restrictions separately; do not assume every dispute notification has the same balance effect.
- Block spending when funding is reversed or disputed as appropriate, preserve debt already incurred by prior purchases, and provide a restricted reconciliation command for recovery.

Acceptance: a valid completed-but-unpaid session gives zero credit; invalid signatures fail; replaying ten events or racing webhook and status reconciliation posts one deposit; reversals cannot leave already-returned money spendable. Follow [Stripe's fulfillment](https://docs.stripe.com/checkout/fulfillment.md?payment-ui=stripe-hosted), [webhook](https://docs.stripe.com/webhooks), [refund](https://docs.stripe.com/refunds), and [dispute](https://docs.stripe.com/disputes/how-disputes-work) contracts.

**BE-05 — Provide a curated live service catalog and discovery**

Priority: P0. Depends on BE-01 and INT-01; allowance data depends on BE-08.

Action items:

- Define an operator-managed catalog record with ID, description, search keywords, request schema, response format, HTTP method/URL, retail/provider amount, payment recipient, chain/token, and enabled state.
- Implement authenticated keyword discovery using the existing search behavior where suitable. Return the full retail price, input schema, and affordability against wallet and agent allowance. Keep discovery free.
- Allow only explicitly enabled live providers in live mode. Do not import arbitrary Creator URLs or fictional demo services into the live catalog automatically.
- Pin registered destinations and payment terms; reject arbitrary model-supplied URLs, redirects, unsupported tokens, and invalid schemas. Version or snapshot terms for each accepted purchase.

Acceptance: an LLM can select a usable service from discovery alone; a disabled/unapproved service cannot execute; discovery changes no balance and makes no paid provider calls; a price increase beyond the approved maximum prevents payment.

**BE-06 — Execute purchases and settle providers through MPP**

Priority: P0. Depends on BE-02, BE-05, and BE-08. Can use a simulated payment adapter during development; live acceptance requires the configured funded provider path.

Action items:

- Implement account-backed `/v1/execute` and `/v1/executions/{id}`. Validate inputs and reserve retail credits before any provider payment; return 202 with an execution ID for unfinished work.
- Reuse the MPP challenge/credential/receipt mechanics while introducing explicit settlement configuration for mainnet and isolated testnet. Validate network, allowed token, amount, recipient, request binding, and confirmed transfer.
- Persist execution terms, signed payment credentials, transaction references, provider receipts, and response results durably. Keep sensitive payment credentials out of customer responses and routine logs.
- Persist provider result and debit capture atomically when fulfillment completes. Return both the user's ledger receipt and the outgoing provider receipt; do not invent the old agent-to-platform on-chain receipt.
- Use one settlement signer worker in the MVP, with a database-backed lease/lock preventing a second process from signing concurrently. Add a configured treasury liquidity/fee reserve check before submitting new payments.
- Handle registered method/body conventions through explicit adapters. Support the existing controlled provider contract first; do not claim arbitrary MPP endpoints work without adapter verification.

Acceptance: one successful purchase produces one retail debit and one provider payment; concurrent retries and process restart do not sign a second payment; an unfunded treasury yields no completed user charge; wrong chain/payee/token/amount is rejected before signing. A real-money proof must use an enabled mainnet provider and a genuine service response.

**BE-07 — Reconcile purchases, refund failures, and expose transaction history**

Priority: P0. Depends on BE-02, BE-04, and BE-06.

Action items:

- Implement a durable worker with leases, bounded retries, and startup recovery for reserved payments and interrupted fulfillment. Preserve original payment credentials and idempotency keys.
- Distinguish pre-payment rejection, uncertain settlement, paid-but-pending fulfillment, completed fulfillment, and terminal failure. Reconcile uncertain outcomes through saved transaction/receipt evidence before resolving them.
- On terminal failure, release the reservation or compensate the captured debit exactly once and restore agent allowance once. Keep a linked refund/release record and any separate platform provider loss.
- Add an operator-only CLI to list unresolved executions and perform evidence-backed reconciliation/refund decisions. Late responses cannot capture a refunded execution or trigger another provider payment.
- Implement paginated transaction list/detail with stable cursors, filters, linked records, and safe receipts. Persist history independently of application restarts; live accounts have no demo reset operation.

Acceptance: lost provider responses stay pending until reconciled; a confirmed terminal failure restores the $0.40 once; paid provider failures retain provider cost evidence; history explains each wallet delta; an operator can resolve a simulated ambiguous payment without editing the database by hand.

**BE-08 — Issue and enforce capped agent credentials**

Priority: P0. Depends on BE-01 and BE-02.

Action items:

- Extend agent records with name, owner-approved lifetime cap, expiry, spent, and reserved allowance. Reuse existing credential hashes, expiration, and revocation primitives.
- Implement agent listing/creation and credential issue/revoke routes. A credential cannot outlive its grant; all replacement credentials share its allowance.
- Limit machine credentials to balance, discovery, execution, and reading their own executions. Enforce ownership on every identifier lookup.
- Recheck authority in the atomic reservation operation. Revocation prevents new purchases; already-submitted payments must still be reconciled without creating replacement spending authority.
- Add bounded request/body limits and basic rate controls to credential issuance, discovery, top-up creation, and execution. A new idempotency key does not bypass a grant limit.

Acceptance: a $2 grant cannot buy more than $2 cumulatively even after wallet top-ups; two credentials for that grant cannot independently spend $2; expired/revoked credentials cannot reserve; an agent cannot create credits, issue grants, or read another agent's results.

**BE-09 — Prepare the backend for a real-money pilot**

Priority: P0. Depends on BE-01 through BE-08.

Action items:

- Provide repeatable migrations, a local Postgres/worker startup procedure, separate test/live secrets and databases, and an environment-variable reference with placeholders only.
- Add readiness checks for database, payment configuration, worker, and settlement network. Live mode must fail closed on missing persistence, configuration mismatch, or demo credentials.
- Add structured request/execution IDs and operational visibility into unprocessed webhooks, unresolved payments, treasury liquidity, and reconciliation failures without logging secrets.
- Add CI coverage with Postgres for monetary concurrency and recovery paths; retain existing demo tests under their separate mode.
- Document backup/restore, signer access, worker restart, provider enable/disable, and funding-reversal procedures. Complete a restore/restart exercise against non-live data before live use.

Acceptance: a new developer can run the complete stack from documented commands; disabling an integration yields an explicit unavailable state; restarting the API/worker preserves balances and pending work; required database tests run rather than silently skipping. Missing hosting credentials or funded settlement accounts are reported as launch dependencies, not as implemented live capability.

**Integration tickets owned by the coordinating agent**

**INT-01 — Freeze contracts and coordinate parallel work**

Priority: P0. Precedes implementation-agent launch.

Action items:

- Obtain review of the product scope, money model, fee policy, and agent-cap semantics in this document.
- Produce concrete request/response fixtures for every listed route, including errors and states, and agree Pydantic/OpenAPI and frontend type ownership.
- Assign agent 1 exclusive implementation ownership of `frontend/`; assign agent 2 the backend, ledger, settlement, migrations, and backend tests. The coordinator owns MCP/client integration, shared docs, and cross-stack acceptance.
- Define backend-owned schemas as authoritative; frontend fixtures must match them. Route/status changes are communicated before either side adopts them.
- Break work into the milestones below and review actual results after each. Agents report changed files, checks run, unverified dependencies, and contract changes.

Acceptance: both agents receive the same approved contract and can name their dependencies and file boundaries. No agent is spawned before the requested review is complete.

**INT-02 — Connect account-backed MCP tools and the purchasing skill**

Priority: P0. Depends on INT-01; implementation uses BE-05, BE-06, and BE-08.

Action items:

- Add an explicit account mode to the local client/MCP runtime using API base URL and agent credential. This mode never loads a personal crypto key or silently falls back to the demo wallet.
- Expose `balance`, `discover`, `execute`, and `execution_status`. Bind idempotency to a durable local request record so an interrupted tool call can recover its execution without creating a new purchase.
- Update the purchasing skill to check wallet and grant allowance, honor user task budgets, compare combined costs, treat provider content as untrusted evidence, and report charged/refunded/pending amounts.
- Remove testnet/two-hop claims from the account-mode skill. Preserve accurate separate instructions for explicitly selected demo mode.
- Update installer/export and free connection-check flows. Validate supported clients' configuration using placeholders and private local credential storage; never put an actual secret in a skill or example command history.

Acceptance: a fresh client connection discovers services without payment, purchases one with the authorized account, polls pending execution, reports its result/refund accurately, and cannot bypass the server cap. Loss of the local tool response does not cause a duplicate charge on retry.

**INT-03 — Verify the complete product and prepare the review handoff**

Priority: P0. Depends on FE-06, BE-09, and INT-02.

Action items:

- Run the primary journey through the browser, Stripe integration, database, MCP client, and provider adapter. Include both a successful purchase and a terminal failure with refund.
- Test two users, two agents sharing a wallet, concurrent purchases, webhook replays, changed-body idempotency conflicts, expired grants, revocation, and restarts around each external-payment boundary.
- Run frontend tests/typecheck/build, backend lint/tests with Postgres, MCP protocol checks, and browser QA. Keep real-money smoke verification separate from tests with simulated settlement.
- Record proof using safe account/execution/payment references, balances before/after, and provider receipts. Do not report live acceptance until actual configured live services have been exercised.
- Deliver setup instructions, remaining operational dependencies, and the observed test results. Do not automatically publish or initiate unbounded real-money tests.

Acceptance: the primary journey is reproducible, every customer balance change can be traced, and the tested failure paths do not duplicate credits or provider payments.

**Implementation sequence**

| Milestone | Frontend work | Backend work | Coordinator work | Exit condition |
| --- | --- | --- | --- | --- |
| 0 Review and contract | Review page flows | Review states and schema | INT-01 | Scope and API fixtures agreed before spawning the two agents |
| 1 Identity and wallet | FE-01 and FE-02 against agreed fixtures, then real endpoints | BE-01, BE-02, BE-08 | Begin INT-02 client interface | Two users have isolated accounts; grants and wallet arithmetic work |
| 2 Funding | FE-03 | BE-03 and BE-04 | Funding integration checks | Verified payment credits one correct account exactly once |
| 3 Service purchases | FE-04 and FE-05 | BE-05, BE-06, BE-07 | Complete INT-02 | MCP purchase and failure refund appear in the same user's dashboard |
| 4 Live pilot verification | FE-06 | BE-09 | INT-03 | Full acceptance suite passes; live dependencies configured and bounded smoke test recorded |

**Launch dependencies and review decisions**

The code deliverable includes real-money support. Activating a live pilot also requires a claimed production Clerk application, an enabled Stripe account with Link and webhook configuration, a deployment destination with HTTPS, Postgres and worker persistence, and a protected funded mainnet signer. The initial live provider, supported settlement token/network, provider price, and receiving wallet must be explicitly configured. The current fictional testnet providers do not satisfy that requirement.

The user approved the prepaid-credit/treasury separation, platform absorption of processing and network fees, top-up presets, and lifetime grant behavior by authorizing scoped execution. The shared contract sets credential/grant expiry to seven days by default and at most thirty days. Operational retry intervals are bounded configuration values. A maximum amount for real-money smoke verification must still be specified before running that test.

The intended minimum release is a controlled real-money pilot with one or a few operator-configured services. It is not a general marketplace launch. The most substantial work is backend accounting and payment recovery; the frontend can be built concurrently from the agreed contract, but it is complete only after integration with those real states.

**Implementation handoff — October 4, 2026**

Exactly two implementation agents delivered the frontend and backend within the approved boundaries. The coordinator delivered the account MCP adapter, purchasing skill, shared contract, CI and [setup/recovery runbook](account-mvp.md). Source implementation and local automated verification are complete; live acceptance remains open.

| Tickets | Delivered and verified | Remaining acceptance |
| --- | --- | --- |
| FE-01–FE-05 | Real Clerk SDK and lockfile, protected account shell, wallet funding/return, transactions/results, agents/credentials and connection instructions | Configured browser journey through Stripe and the account API |
| FE-06 | 35 frontend tests, clean TypeScript and production build; successful Clerk init and doctor; desktop and 390×844 mobile public/auth views | Authenticated dashboard states and full payment/results journey |
| BE-01–BE-08 | Authenticated API, PostgreSQL accounting, Stripe funding/events/reversals, curated discovery, durable MPP settlement/refunds, bounded grants and rate controls; all 11 real PostgreSQL tests pass | Configured Stripe/provider integration and bounded live-money proof |
| BE-09 | Persistent database volume, migrations, immutable runtime bindings, worker, health/review/reconciliation commands, environment reference, required-Postgres CI; isolated dump/restore and fresh-process recovery pass | Remote CI, production configuration and funded settlement verification |
| INT-01 | Reviewed scope and frozen HTTP contract; coordinated two agents and resolved shared-state issues | Complete |
| INT-02 | Explicit account mode, four MCP tools, private credential setup, durable idempotency journal, client installer/check and purchasing skill; 17 client/MCP tests pass | Configured end-user client purchase against the running account backend |
| INT-03 | Real FastAPI/Store/worker acceptance with simulated external payments, successful database restore and full local regression | Complete authenticated browser journey and separately bounded live-money smoke test |

Observed verification for this handoff:

- Full Python regression with required PostgreSQL and the opt-in restore check enabled: **258 passed, 1 skipped**. The remaining skip is the opt-in live MPP payment test. The existing Creator browser tests now pass with workspace access restored.
- Account-specific coverage totals **61 passing tests**: 17 client/MCP, 32 backend component tests, 11 real PostgreSQL acceptance tests, and one database dump/restore and fresh-process recovery test. Coverage includes concurrent balance/cap enforcement, ownership, Stripe replay/reversals, successful purchases, failure refunds, signed-payment recovery, and immutable runtime bindings. External payment responses in these tests are simulated.
- The real PostgreSQL run exposed an SQL keyword conflict in the execution migration. Renaming the internal column to `payment_authorization` fixed it; migration, acceptance and recovery tests then passed.
- Frontend: **35 tests passed**, TypeScript checks pass, and the production build succeeds with the installed `@clerk/nextjs` SDK and regenerated lockfile. Clerk `init` completed after user authentication; `doctor` confirms the linked development application and local keys. Production Clerk remains unconfigured. Keys are ignored by Git.
- Browser QA verified the public homepage and Clerk sign-in on desktop, plus homepage/sign-in/sign-up at 390×844 without horizontal overflow. Protected dashboard routes redirect signed-out visitors to sign-in. This exposed and fixed a local startup loop by binding Next.js to the same `localhost` hostname used by Clerk requests. The API proxy reports unavailable while its backend origin is unconfigured. Authenticated dashboard and payment flows still require the external services.
- Ruff, `git diff --check`, and `uv lock --check` pass. npm audit reports two moderate development-tool advisories in the existing Vitest version; its production dependencies have no reported advisories. A forced major test-runner upgrade is outside this iteration.
- CI now requires the PostgreSQL accounting suite and full Python regression, plus frontend install, tests, build and typecheck. Remote CI has not yet been observed. The restore exercise ran locally against a unique synthetic schema and temporary database; it did not change existing account data or contact payment providers.
- No live payment or production deployment was performed. The frontend production preview and local PostgreSQL are available for continued integration. Production Clerk, Stripe/Link/webhook setup, an approved provider, a protected funded treasury, deployment configuration, and an explicit smoke-test budget remain required.

Next acceptance step: configure the external services, complete the authenticated browser-to-MCP purchase and failure-refund journey, then run a separately budgeted real-money smoke test. Automated payment doubles and development Clerk configuration are not evidence of live-money acceptance.
