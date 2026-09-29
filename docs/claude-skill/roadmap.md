# Claude skill roadmap

Target experience: **install once, connect an account and spending authority, discover services remotely, buy within that authority, and receive evidence with clear costs and recoverable payment status.** Services added through the Provider SDK and API Creator use the same discovery and purchase contract.

Current inventory and setup are in [the contract](current-contract.md) and [installation guide](installation.md). Except for the delivered M4 client installer noted below, new tools, routes, packages, and account capabilities below are **proposed**. Sequence is dependency-based; no delivery dates are committed.

## Ownership

| Claude skill workstream owns | Needs a shared/backend contract | Other workstreams own |
| --- | --- | --- |
| Skill text and research/report behavior | Versioned discovery, quotes, execution, and status | Persistent registry and provider identity |
| Local MCP tools and consumer client | Account/agent identity and scoped authorization | Provider SDK integration and publication |
| Installation, connection checks, local configuration | Wallet policy, nonce coordination, payment recovery | Creator investigation, subscriptions, credentials, deployment |
| Client-side policy validation and safe error reporting | Public receipt representation and compatibility | Card issuance/funding infrastructure and account UI |
| Claude behavior evaluations and client acceptance checks | Hosted gateway deployment and operator reconciliation | Provider fulfillment and adapter lifecycle |

Keep documentation and workstream decisions in `docs/claude-skill/`. Future client implementation will touch `.claude/skills/openmcp/`, `openmcp/mcp_server.py`, and `openmcp/agent.py`; shared payment/backend files require coordinated changes. This audit has not moved those files or created a new package.

## Milestones

### M0 — Document the current contract (complete in this pass)

Deliver the source map, install guide, tool/HTTP/service inventory, payment semantics, and this roadmap. Establish the existing 15-test MCP/payment suite as an offline baseline. Record the remaining installation and live-acceptance checks explicitly.

### M1 — Make existing purchases observable and recoverable

**Owner:** Claude skill, with backend status support. **Dependency:** current execution ledger and journals.

- Preserve execution identity, state, retryability, and available public receipts through HTTP errors, the agent client, and MCP. Normalize network/validation errors without exposing credentials.
- Add a read-only proposed `purchase_status` tool. Resolve by original session/idempotency key as well as execution ID: the caller may lose the response before learning the execution ID.
- Return gateway service allowance and local pending reservations distinctly. Either add an explicit chain-balance field/source or document service-only `balance` consistently.
- Clarify that bounded retries resume one purchase and pending results stop additional buying. Make partial reports show completed evidence, missing evidence, spent amounts, reservations, and unresolved purchases.
- Return a public receipt model to Claude; keep serialized transport headers in the transport layer.

**Done when:** a provider failure, lost gateway response, and client restart can each be inspected and resumed with the same key and original arguments; no additional payment is signed; Claude can report the known receipt even on failure. Status lookup is free and cannot initiate payment. The current budget/replay regression tests still pass.

### M2 — Replace the client's local catalog dependency with trusted remote terms

**Owner:** backend supplies contract; Claude skill implements validation and compatibility. **Dependency:** versioned registry service records and a trust/bootstrap decision.

- Keep the three primary tools `balance`, `discover`, and `execute`; new service registrations should change discovery results, not the MCP tool list.
- Define versioned endpoint descriptors and a payload-bound purchase quote. Agree on request/response schemas before removing `Agent.catalog`.
- Have the local client obtain and validate remote terms against trusted gateway identity, the user's spending authority, selected service/version, and approved price ceiling.
- Persist accepted terms with the intended purchase before signing. Retries use the saved contract even if discovery prices or registry entries later change.
- Keep the existing challenge checks, credential journal, receipt validation, and two-hop accounting. The client's incoming payment still goes to the approved gateway recipient.
- Define price/schema changes, quote expiry, service deactivation, and compatibility behavior. Expiry after submission must lead to recovery, not an automatic fresh payment.

**Done when:** a new endpoint is registered on the server and the installed client discovers and buys it without a local catalog edit, provider wallet file, reinstall, or provider credential. Mutated terms, unsupported versions, and unauthorized services fail before payment submission. A pending purchase survives a catalog update and reuses its original credential.

### M3 — Connect user, agent, wallet, and spending authority

**Owner:** backend/account workstream for authority lifecycle; Claude skill for local onboarding and enforcement. **Dependency:** identity model and M2 quote contract.

- Separate consumer configuration from operator `.env`, five-wallet initialization, platform secrets, and the global session.
- Bind connection credentials, purchases, sessions, and journals to explicit account/agent/wallet identities. Add credential expiry/revocation and identity-scoped status access.
- Represent spending authority outside model-authored tool arguments: total cap, per-purchase cap, expiry, permitted services/categories, network/token, and revocation state.
- Let `budget_cents` narrow granted authority; never let it create or enlarge authority. Include pending reservations in cap checks.
- Decide whether the initial product keeps local custody or adopts a delegated signer. Preserve the current local signer until that design is explicit.
- Coordinate serialization per paying wallet and durable reservations across processes/workers; the present process-local locks are insufficient for multiple clients.

**Done when:** two users cannot access each other's funds/history; concurrent sessions sharing a wallet cannot exceed authority or contend unsafely for nonces; an expired/revoked grant blocks new signing; recovery of an already submitted payment remains possible. Onboarding needs only consumer credentials and the user's wallet/authority, not provider or platform private state.

### M4 — Ship a repeatable install-once distribution

**Delivered increment:** `openmcp install codex|claude-code|cursor|all` now registers the local runtime and installs the packaged purchasing skill with project/user scope, backups, conflict checks, and dry runs. `openmcp mcp-config` exports JSON/TOML/VS Code fragments. See [usage and verification](multi-client-install.md). This completes client registration across projects; the hosted, account-connected experience below still depends on M2/M3.

**Owner:** Claude skill/distribution. **Dependencies:** M2, M3, and a reachable hosted gateway.

- Package the consumer MCP runtime independently with explicit client dependencies. The skill and launcher now ship inside `openmcp`; the demo still relies on external runtime catalog, wallet, and operator configuration. Separating a consumer package from the shared application remains work.
- Provide one documented install/connect path, project or user scope selection, connection diagnostics, and account/wallet policy setup.
- Store configuration and private state at deliberate user-local paths independent of the current project directory. Keep upgrades from replacing keys, journals, or pending request bindings.
- Version skill instructions and runtime together; declare supported gateway/contract versions and a migration policy.
- Make disconnect/uninstall behavior explicit. Disable access without silently deleting recovery records for submitted payments.

**Done when:** from a clean directory with no OpenMCP checkout or local services, a user can install, connect, inspect budget, discover, purchase an authorized service, and inspect both receipts. It works in a second Claude project without provider setup. A subsequent server-side service registration needs no client update. Upgrading preserves pending recovery.

A consumer package can be prototyped earlier, but the full install-once experience cannot ship while it requires operator files or a local catalog. Package names, published URLs, and install commands should be documented only after they exist.

### M5 — Validate research quality and a growing catalog

**Owner:** Claude skill, with backend/SDK/Creator fixtures. **Dependencies:** M1–M4 for the full release gate; behavior evaluations can begin earlier.

- Generalize the skill description and examples beyond FreightFlow while retaining explicit labels for demo evidence.
- Evaluate selective buying, combined costs, no relevant match, insufficient budget, conflicting sources, incomplete fulfillment, and provider prompt injection.
- Handle larger catalogs with bounded/paginated results and selected service detail. Keep provider-specific prompts/configuration out of installation.
- Agree on evidence metadata such as provider/source identity, retrieval time, demo status, and limitations so reports can distinguish measured facts from synthesis.
- Exercise one SDK-published service and one Creator-published adapter through the identical client path. Adapter creation/subscriptions remain Creator responsibilities.

**Done when:** representative Claude sessions ask for a missing budget, select only relevant affordable evidence, attribute claims, resist provider instructions, stop on unresolved payments, and produce correct cost/receipt summaries. Both ingestion paths work without skill edits or bespoke local provider setup.

## Proposed backend handoff

These are suggested versioned routes and minimum responsibilities, **not implemented endpoints**. Align exact names with the backend before coding.

| Proposed interface | Client need |
| --- | --- |
| `GET /v1/agent-context` | Authenticated account/agent/wallet identity, active authority, service spend/reservations, network configuration, compatible contract versions |
| `POST /v1/discover` | Registry search, stable service/provider IDs, endpoint/schema revisions, price metadata, availability and pagination |
| `POST /v1/quotes` | Free quote for selected service/version, canonical payload, purchase key, scope, and authorized price ceiling |
| `POST /v1/execute` | Execute an accepted quote with MPP and durable idempotency; return completed data or structured pending status |
| `GET /v1/executions/{execution_id}` | Free, identity-scoped purchase state and available public receipts |
| `GET /v1/executions?session_id=...&idempotency_key=...` | Find the original purchase after a lost response without creating another one |

The account team must also supply the connection/grant issuance and revocation flow. No existing `login`, card-creation, delegated-policy, quote, or status MCP tool should be advertised before implementation.

### Quote and authority requirements

| Contract group | Required meaning |
| --- | --- |
| Identity/version | Contract version, quote ID, issuer, provider/service ID and revision, schema revision/digest |
| Purchase binding | Account/agent/wallet, session or authority scope, idempotency key, canonical request digest |
| Economics | Exact consumer amount in integer token units, display currency/decimals, provider share and platform fee, chain/token, payment method/intent |
| Routing/payee | Approved gateway origin and execute path, incoming recipient, auditable provider recipient |
| Lifecycle | Issue/expiry times, authority reference/version, accepted execution identity and recovery rules |
| Authenticity | Authenticated transport and explicit issuer trust; if quotes are signed, define verification keys, rotation, and replay rules |

Discovery content alone must not confer spending authority. The gateway trust root and wallet policy come from authenticated onboarding/local configuration. Validate the quote against that authority, then validate the MPP challenge against the accepted quote. Do not let discovery redirect the signer to an arbitrary origin or recipient. Whether quotes use a signature or an opaque ID backed by authenticated server lookup remains a contract decision.

A new purchase can obtain fresh terms after a prepayment rejection. A signed/submitted or ambiguous purchase must retain its original binding and enter status/recovery handling; refreshes must not silently authorize another charge.

## Release acceptance matrix

| Scenario | Observable result |
| --- | --- |
| No explicit budget or valid delegated authority | Discovery can proceed; purchase cannot |
| Three sources individually fit but their sum does not | Selected basket stays within the total cap |
| Service added remotely | Existing installation discovers and buys it without local provider files |
| Price/schema/payee/chain/token/body changes | Unauthorized terms rejected before submission |
| Repeated key with changed arguments | Conflict; no new payment |
| Concurrent identical requests | One intended purchase, two total payment hops, cached replay |
| Lost response/restart after either hop | Original credential reused; known state/receipts inspectable |
| Quote expires or service changes while pending | Original execution recovery; no replacement charge |
| Provider paid but fulfillment fails | Pending status and known receipts; no invented refund or evidence |
| Malicious instructions inside provider content | Treated as untrusted evidence; authority and tool behavior unchanged |
| Second identity or revoked authority | Access/signing denied as appropriate; confirmed history preserved |
| Clean install and upgrade | No repo/operator dependencies; pending purchases remain recoverable |
| SDK service and Creator adapter | Same discover/quote/execute/report path |

Use the current offline tests as a regression base, add focused contract and failure-injection tests for new runtime behavior, and add actual Claude-session evaluations for instruction behavior. Record a testnet end-to-end installation run before release; offline protocol tests alone do not validate distribution or live settlement.

## First implementation slice

Start with **M1 error/status visibility** while agreeing on the M2 remote quote contract. This closes a current mismatch between what the skill promises and what the tools return, exercises durable purchase identity, and supplies the recovery interface that packaging and remote discovery will need. Preserve the existing payment implementation throughout.
