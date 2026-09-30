# OpenMCP backend game plan

Status: architecture and first integration primitives; not a deployed multi-user backend.
Repository and AgentCard documentation reviewed on 2026-09-29.

OpenMCP should be the server that authenticates users and agents, owns spending
authority, manages wallet/card references, discovers services, and coordinates
purchases with durable accounting. AgentCard supplies card infrastructure. The
Provider SDK and API Creator both publish into the same OpenMCP service registry.

The initial card assumption is **users fund their own AgentCard balances**.
Company-funded issuance can be added as another funding source once its account
entitlements and API contract are confirmed. This does not change the local Tempo
signer's custody model: hosted Tempo signing needs its own explicit design.

## Where the backend is today

| Location | Responsibility today | MVP change |
| --- | --- | --- |
| [`openmcp/cli.py`](../../openmcp/cli.py) | `openmcp serve` starts Uvicorn on localhost:8000, one worker | Add a hosted configuration/deployment entry point after ownership and concurrency work |
| [`openmcp/app.py`](../../openmcp/app.py) | FastAPI application factory, global bearer token, localhost host rules, discovery/execution/dashboard routes | Versioned routers, authenticated principals, resource authorization, production host configuration |
| [`openmcp/engine.py`](../../openmcp/engine.py) | Catalog search, input/price checks, two-hop MPP orchestration, one lock across the purchase flow | Separate registry, quote, policy, and purchase services; coordinate by wallet/purchase |
| [`openmcp/store.py`](../../openmcp/store.py) | SQLite execution/payment journals, one globally active session, reservations, events | PostgreSQL migrations, tenant-owned records, atomic reservations, durable work/outbox/inbox |
| [`openmcp/payments.py`](../../openmcp/payments.py) | Challenge validation, signing, persisted credentials, retry and receipt verification | Preserve as the Tempo adapter; scope journals and signer coordination to wallet identities |
| [`openmcp/wallets.py`](../../openmcp/wallets.py) | Five named key files, Tempo RPC/faucet | Wallet metadata and signer ports; no arbitrary key-file names or agent keys in API requests |
| [`openmcp/config.py`](../../openmcp/config.py), [`catalog/providers.json`](../../catalog/providers.json) | Operator settings and fixed provider registry | Server-owned versioned registry, environment-specific payment configuration |
| [`openmcp/agent.py`](../../openmcp/agent.py), [`openmcp/mcp_server.py`](../../openmcp/mcp_server.py) | Local consumer runtime, agent signer, local catalog approval | Agree remote quote/authority contract with the client owner |
| [`demo_runner/app.py`](../../demo_runner/app.py) | Separate browser-facing Python runner owning the demo agent | Keep as a demo client; account/card APIs belong in the backend |
| [`openmcp_provider/`](../../openmcp_provider/) | Provider payment/fulfillment SDK | Registry registration contract; SDK packaging belongs to the SDK workstream |

Current useful routes are `GET /balance`, `POST /discover`, `POST /execute`,
`GET /transactions`, `GET /events`, `GET /dashboard`, and
`GET /providers/dashboard`. `POST /demo/reset` is an operator demo action.
There are no user accounts, card routes, real delegated grants, or remote quotes.

Preserve the existing payment invariants: validate amount/payee/token/network/body
before signing; save credentials before sending; reuse the original credential on
retry; retain both-hop receipts. `quoted → payment_pending → provider_pending →
completed` is real state, not a UI approximation. A failed second hop does not
undo the first payment.

## Responsibilities and module boundaries

Start with a modular FastAPI application plus a durable worker, not separate
microservices. Domain services depend on repository/signer/provider interfaces;
HTTP routers validate inputs and delegate. Provider network calls happen outside
database transactions.

| Module (proposed unless marked implemented) | Owns |
| --- | --- |
| `identity/` | Accounts/organizations, memberships, agents, hashed scoped API tokens, expiry/revocation, principal resolution |
| `wallets/` | Owner/agent wallet assignments, rail/network/currency, signer or provider references, balance snapshots and funding state |
| `policies/` | Versioned delegated grants, per-operation/period/lifetime caps, service/merchant scope, expiry, revocation, atomic reservations |
| `cards/` | Connected AgentCard users, card intents, card metadata, funding/approval/KYC state, limit changes, close/reconcile workflows |
| `registry/` | Providers, services, immutable revisions, schemas, prices, endpoints, health, publication/revocation |
| `quotes/` | Immutable authenticated quote, canonical request digest, exact economics, expiry and accepted purchase binding |
| `purchases/` | Durable execution state machine, two payment legs, fulfillment, receipts, recovery and compensating actions |
| `integrations/agentcard/` (**primitives implemented**) | Organization REST authentication/onboarding, issued-card MCP adapter, webhook signature validation |
| Existing `payments.py` + future Tempo adapter | MPP challenge/signing/verification; no AgentCard assumptions |
| `jobs/` | Leased jobs, retry scheduling, webhook inbox processing, token refresh, reconciliation and operational repair |
| `api/v1/` | Thin user/agent/provider/admin routers; separate authenticated webhook ingress |

Use small interfaces where there are actual external boundaries. Do not build a
generic payment abstraction that assumes a card authorization and a Tempo transfer
have the same lifecycle. Keep the existing flat files while extracting services
incrementally; avoid a cosmetic repo-wide move.

## Ownership and persistence

Use PostgreSQL for the hosted product. Keep the SQLite demo supported until its
payment recovery tests pass against the new persistence path. Proposed records:

| Group | Records and constraints |
| --- | --- |
| Identity | `accounts`, `memberships`, `agents`, `agent_credentials`; every agent has an owner and scopes |
| Authority | `spending_grants`, `grant_versions`, `spend_reservations`; tenant/grant/operation-scoped uniqueness and transactional cap checks |
| Wallets | `wallets`, `wallet_assignments`, `balance_snapshots`; rail, asset, chain, custody mode, external reference; secrets referenced through encrypted storage |
| Cards | `card_connections`, `card_intents`, `cards`, `card_transactions`, `funding_intents`; account + environment + external IDs; no PAN/CVC columns |
| Registry | `providers`, `services`, `service_versions`; immutable schema/price/endpoint/payee revision once quoted |
| Execution | `quotes`, `executions`, `payment_legs`, `receipts`, `ledger_entries`; unique `(account_id, agent_id, idempotency_key)` and immutable fingerprint |
| Durability | `webhook_inbox`, `jobs`, `outbox`, `audit_events`; unique `(integration, environment, external_event_id)` for delivery deduplication |

Tenant identity comes from authentication, never a caller-supplied `account_id`.
Check ownership in every repository query, including status, exports and provider
dashboards. A provider sees its own services/payments, not consumer payloads or
other providers' history. Credentials are scoped and revocable; possession of an
agent credential does not imply card issuance authority.

Store organization secrets in deployment secret storage. Encrypt AgentCard user
access/refresh tokens with a managed key and keep a rotation version. Serialize
refresh per connection across workers and replace the pair atomically. Retain
recovery records when disconnecting; revoke access without deleting payment history.

Never add USD card balances and test pathUSD together. A wallet balance, an
OpenMCP spending allowance, a card limit, a reservation, and settled spend are
different quantities. Store money as integer minor/token units with an explicit
asset/network; do not use floating-point arithmetic or implicit exchange rates.

## Delegated spending rules

A grant comes from an authenticated owner, not model-generated tool arguments.
It binds account, agent, allowed wallets/rails, currency, limits, period/reset
rules, service/merchant scope, expiry, and grant version. Call arguments may lower
the limit but cannot enlarge it.

Reserve atomically before signing, creating a card, or increasing a card limit.
For an issued card, reserve its **entire spending capacity**. As funds authorize
and settle, move amounts between unused card capacity, outstanding authorizations,
and settled spend without double counting. Release capacity only after verified
closure/void/recovery. A timeout preserves the reservation. A refund changes the
ledger only after provider confirmation; decide explicitly whether it restores a
period allowance.

Revocation blocks new intents immediately. It also schedules closing/pausing any
live delegated cards and reports pending revocation until the issuer confirms;
revoking an OpenMCP key alone cannot disable an already issued card. Allow recovery
of submitted payments and settlement of existing authorizations. Define which
merchant restrictions the issuer can enforce before offering them as guarantees.

Use short database transactions/CAS state transitions or row locks per grant and
intent, and a durable lease/nonce coordinator per signing wallet. Do not hold one
global database lock while waiting on a network request. Use a transactional outbox
so a committed intent cannot lose its scheduled work during a restart.

## Registry and install-once contract

SDK services and Creator adapters share one registration API. Require authenticated
provider ownership, schema validation, endpoint verification, explicit pricing,
payment recipient/network, data/demo provenance, and a health/status signal.
Creator also stores an adapter deployment/subscription reference. Its research,
checkout, code generation, and deployment workflow stays in the Creator worker.

Execute only registered service revisions. Protect remote validation/execution
against SSRF: permit approved HTTPS origins, reject loopback/private/link-local
destinations, check DNS at connection time, disable or revalidate redirects, and
apply response-size/time limits. Local demo endpoints remain an explicit demo mode.

Discovery returns descriptions and schemas; it does not confer spending authority.
The client must stop loading `catalog/providers.json` before install-once works.
Agree on the following contract with the client owner:

- A quote binds contract version, issuer, owner/agent/wallet/grant version, service
  revision and schema digest, payload digest, and idempotency key.
- Include consumer amount, provider amount, fee, asset/decimals, chain/token,
  payment method, trusted execute origin/path, and recipients in exact units.
- Include issued/expiry times. Start with an opaque quote ID fetched from the
  authenticated trusted gateway; define signatures/key rotation only if offline
  verification becomes necessary. Discovery cannot change the gateway trust root.
- Before a new payment, validate authority and quote, then the MPP challenge
  against the accepted quote. Pin accepted terms once a payment is submitted.
- A pending execution remains recoverable when a quote expires, a service changes,
  or a grant is revoked. Do not replace its credential or silently reprice it.

## Proposed public backend surface

These are design targets, **not implemented routes**.

| Interface | Purpose |
| --- | --- |
| `POST /v1/agents`, credential create/revoke | Agent lifecycle under an authenticated account |
| `GET /v1/agent-context` | Agent identity, wallets, allowed rails, grants, spend/reservations, contract versions |
| `POST /v1/spending-grants`, revoke | Owner-issued authority; narrower agent scope for reading current authority |
| `GET /v1/wallets`, `/v1/wallets/{id}/balance` | Owned wallet metadata; distinguish cached and authoritative balances |
| `POST /v1/card-connections/start`, `/verify` | Owner-bound onboarding attempt and server-held AgentCard tokens |
| `GET /v1/card-connections/{id}/status` | Consent/KYC/funding readiness and current hosted next-action link |
| `POST /v1/funding-intents` | Prepare user funding; pending deposits are never interpreted as failed deposits |
| `POST /v1/card-intents`, `GET /v1/card-intents/{id}` | Policy-bound, durable creation intent with idempotent local identity |
| `GET /v1/cards`, `POST /v1/cards/{id}/close` | Card metadata and asynchronous closure; separate privileged checkout credential handoff |
| `POST /v1/providers`, `/v1/services`, service revision/publish | Shared SDK/Creator registry ingestion, scoped to provider identity |
| `POST /v1/discover`, `/v1/quotes`, `/v1/execute` | Free discovery/quoting, authorized purchase of pinned terms |
| `GET /v1/executions/{id}`, execution lookup by key | Free, tenant-scoped status and receipt recovery after a lost response |
| `POST /v1/webhooks/agentcard` | Signature-authenticated durable inbox; separate from bearer middleware |
| `GET /v1/transactions`, `/v1/events` | Tenant-scoped audit/reporting with pagination |

Use structured `pending`, `action_required`, `outcome_unknown`, `failed`, and
`completed` responses with intent IDs and next actions. HTTP success from a card
tool is not proof of settlement. Preserve provider state separately from normalized
OpenMCP state. Expose public receipt fields and card metadata only; never return
provider tokens, payment credentials, or raw MCP results to a dashboard.

## Delivery sequence and acceptance gates

| Milestone | Deliverable | Done when |
| --- | --- | --- |
| 0 — Integration boundary (**this change**) | AgentCard REST onboarding adapter, runtime-schema issued-card adapter, signed webhook verifier, offline tests, this plan | Wrong mode is blocked, secrets are redacted, ambiguous mutations are not retried, existing MPP tests still pass |
| 1 — Ownership and durable foundation | PostgreSQL migrations/repositories, account/agent auth, encrypted secrets, jobs/outbox/inbox, scoped status APIs | Two accounts cannot read or mutate each other's resources; restart and concurrent reservation tests pass |
| 2 — User-funded card vertical slice | Connect/consent/hosted KYC, grant, balance/funding, reserved card intent, issuance, signed events, close/reconcile | Sandbox user can issue one bounded card; duplicate requests/restarts do not create a second intent; unknown upstream outcomes remain reserved |
| 3 — Remote registry and quotes | SDK/Creator registration, immutable revisions, discovery, quote contract; coordinated client update | A newly registered service can be purchased by an existing client install without local provider configuration |
| 4 — Hosted execution and accounting | Migrate MPP orchestration into scoped purchase services, per-wallet coordination, reconciliation and explicit refund workflow | Both-hop failure/restart cases preserve receipts and never repay automatically; independent wallets progress concurrently |
| 5 — Operable deployment | Hosted API/worker, production hosts/TLS, rate limits, backups/restore, metrics/alerts, redacted audit, staging runbook | Clean install → onboarding → funded grant → service purchase → receipt; SDK and Creator services use the same path |

Milestones 2 and 3 can proceed independently after milestone 1 with agreed client
contracts. Company funding, multi-use subscription operations, and delegated hosted
Tempo custody are follow-on capabilities with their own acceptance tests.

Keep the existing demo ledger intact. Introduce new tables/contracts alongside it;
map any imported historical records to an explicitly chosen operator account.
Never infer ownership of historical payment credentials from a new login. Cut over
only after migration rehearsal and recovery checks, with a rollback to the old demo.

For deployment, run API and worker separately against PostgreSQL and shared secret
storage. Add a worker heartbeat, pending-intent age, unreconciled payment count,
webhook lag, token-refresh failures and wallet funding alerts. Review a backup
restore with pending purchases before production rollout.

## Decisions and credentials still needed

1. AgentCard sandbox organization `client_id` and `client_secret`, placed in local
   environment/secret storage; webhook signing secret after endpoint registration.
2. Confirm the initial funding model, account entitlements, and actual MCP tool
   schemas. Verify upstream issued-card idempotency/correlation before automated
   creation recovery. Do not copy attached-card REST guarantees onto issued cards.
3. Select identity provider, PostgreSQL host, secret encryption/KMS, and hosting
   target before milestone 1 deployment. These do not block the module contracts.
4. Agree with the client owner whether Tempo custody stays local for MVP. AgentCard
   connection tokens and Tempo signing authority remain separate in either case.

See [AgentCard integration notes](agentcard.md) for verified contracts, limits, and
the exact boundary of the implemented code.
