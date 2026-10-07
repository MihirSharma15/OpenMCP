# OpenMCP

The account MVP adds Clerk sign-in, Stripe-funded USD credits, capped agent credentials,
transaction history, and outgoing MPP purchases. See [account setup](docs/account-mvp.md)
and the [implementation tickets](docs/mvp-tickets.md). It runs in explicit account mode;
the testnet demo below remains a separate flow. Live use requires production configuration,
a funded platform treasury, and an enabled live provider.

[DataForSEO setup](docs/dataforseo.md) adds Google search, keyword metrics, and related
keyword ideas to account-mode discovery and purchases. It uses prepaid API credentials;
these services do not require a crypto treasury. The checked-in catalog uses the free sandbox.

Get paid for data you already own. This POC demonstrates **MPP on both payment hops**, using real transactions on **Tempo Moderato testnet**. No Stripe account, card, Connect account, or real money is involved.

```text
Claude Code + local agent wallet
    │ Request → 402 challenge → signed credential → receipt
    │ 0.40 test pathUSD via MPP
    ▼
OpenMCP server + its own wallet
    │ Request → 402 challenge → signed credential → receipt
    │ 0.36 test pathUSD via MPP
    ▼
Provider's paid API + recipient wallet

OpenMCP retains 0.04 test pathUSD before network fees.
```

Claude discovers providers and calls `execute`. The **local MCP process** signs the agent's incoming payment. The server receives it, then acts as an independent MPP client to pay the provider. Both exchanges use the official `pympp` SDK and return receipts with distinct on-chain transaction references. The server never loads the agent's signing key.

This repository includes the Claude skill, local MCP tools, discovery, budget enforcement, payment middleware, frontend APIs, and the provider service described by [docs/provider-contract.md](docs/provider-contract.md). The three provider routes return clearly labeled fictional FreightFlow evidence.

The [backend game plan](docs/backend/README.md) maps this demo to a hosted, multi-user
service for agent wallets, delegated spending, cards, and a remote API registry.
[AgentCard integration notes](docs/backend/agentcard.md) describe the isolated,
offline-tested integration primitives and what still needs to be wired into the backend.

## API Creator: infrastructure direction

**Use Modal for Creator workers and generated API hosting, and third-party providers
for inference, managed browser sessions, and subscription billing.** OpenMCP owns
the workflow, registry, spending policy, and pay-per-call integration. The
[API Creator README](openmcp_creator/README.md) explains the implementation, how to
run it, and the handoff for Modal, managed browsers such as Browserbase, and AgentCard.

The local Creator researches URLs with a browser and configurable inference,
generates validated adapters, and registers paid FastAPI endpoints for discovery
and execution. Modal deployment, managed browser integration, and automatic paid
subscriptions are the next integrations; they are not running in this commit.

## Prices

All previous API prices and absolute platform fees have been divided by ten. The platform percentage remains 10%.

| Endpoint | Claude → OpenMCP | OpenMCP → provider | Gross platform fee |
| --- | --- | --- | --- |
| Operational health | 0.40 | 0.36 | 0.04 |
| Legal liabilities | 0.50 | 0.45 | 0.05 |
| Competitor market share | 0.30 | 0.27 | 0.03 |
| **Total** | **1.20** | **1.08** | **0.12** |

Amounts are valueless **test pathUSD**. A 15.00 service budget has **13.80** remaining after the three purchases. Small testnet network fees also come out of the paying wallets, so actual wallet deltas differ slightly from the service prices. `price_cents: 40` means 0.40 test pathUSD; the token has six decimals, so the MPP challenge contains `amount: "400000"`.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and network access to Tempo testnet:

```bash
uv sync
uv run openmcp init
uv run openmcp fund
uv run openmcp doctor --chain
uv run openmcp serve
```

`init` creates five fresh wallets in `.openmcp/wallets/`: `agent`, `openmcp`, `operations`, `legal`, and `market`. Repeating it preserves existing keys. Each private key file has mode 600; the wallet directory has mode 700 and is gitignored. Only `public.json` contains public addresses. It also initializes `.env` with a local connection token and an MPP challenge-signing secret. Keep the entire `.openmcp` directory private; payment journals contain signed payment credentials.

`fund` uses the **testnet faucet** to fund the two paying wallets. Providers start at zero and receive payments. The faucet grants a large test balance; the independently enforced **15.00 service budget** is the amount Claude may spend during a run. The UI exposes the actual wallet balance separately from the budget. No mainnet chain is permitted; both challenge policy and the signer pin chain **42431**.

The server listens at `http://127.0.0.1:8000`. Interactive REST docs are at `/docs`; authorize with `OPENMCP_API_TOKEN` from `.env`. This is the one local OpenMCP connection credential, not a provider billing key. MPP payment credentials use `Payment-Authorization` on this hop, leaving `Authorization` for the connection token. Providers use ordinary MPP `Authorization: Payment …`.

If upgrading from the earlier card-based draft, run `init` again. It creates the MPP secrets/wallets and selects a new ledger when the old default database was configured. Existing unrelated `.env` settings and the old database are preserved but unused. Restart the running server after upgrading.

## Provider service

Run `uv run python -m scripts.run_providers` to start the single MPP provider app on port 9001 and the three traditional mock APIs on ports 9101–9103. The provider reads only `.openmcp/wallets/public.json`; its challenge secrets, replay database, and fulfillment database persist privately under `.openmcp/provider/`. Start `uv run openmcp serve` separately, then use `uv run openmcp demo`.

## Live frontend demo

The `/demo` page is an observer-only wallet view. It shows the active service budget, the agent's separate on-chain testnet balance, and recent purchases with both Tempo receipt links. Start the full Python stack in one terminal:

```bash
uv run python -m scripts.run_demo
```

Then start Next.js separately:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:3000/demo`. Type a positive USD session budget, then select **Apply**. The typed amount becomes the active session ceiling. Remaining balance falls as purchases settle; later `execute` calls cannot raise or replace that ceiling. Applying starts a new session and clears its transaction list; it does not reverse on-chain transfers.

Make purchases through Claude Code or another MCP-compatible agent as described below. The page is safe to leave open while the agent buys: its local runner has only the gateway connection token, never loads a wallet or signs a payment, and exposes only sanitized dashboard/reset operations through the same-origin `/api/runner/*` rewrite.

Open `http://127.0.0.1:3000/providers` for the provider workspace: historical earnings, incoming payments, service prices, and on-chain wallet balances. Switch providers, filter dates and payment status, inspect both-hop receipts, or export payment history as CSV. The dashboard automatically updates as the agent buys data. Earnings history survives demo resets; current-session earnings and on-chain balances are labeled separately. This local operator view uses the same Python stack and Tempo testnet payments as the demo.

## Codex, Claude Code, Cursor, and other MCP clients

After completing the runtime setup above, install the local MCP tools and purchasing skill across your projects:

```bash
uv run openmcp install all --scope user --dry-run
uv run openmcp install all --scope user
```

Use `codex`, `claude-code`, or `cursor` in place of `all` to select one client. Project scope, conflict handling, backups, and JSON/TOML/VS Code exports are covered in the [multi-client installation guide](docs/claude-skill/multi-client-install.md). Restart the client and enable the server. The installer keeps secrets in the existing runtime and preserves unrelated client settings. These clients share the demo wallet; use only one purchasing client at a time.

### Original Claude Code repo setup

Start Claude Code in this repo and enable the checked-in `.mcp.json` server. The skill at [.claude/skills/openmcp/SKILL.md](.claude/skills/openmcp/SKILL.md) can be invoked with `/openmcp`.

Alternatively, register using an absolute repo path:

```bash
claude mcp add --transport stdio openmcp -- uv run --directory /absolute/path/to/openmcp openmcp mcp
```

The local process loads only the **agent wallet** for its paid tool. It obtains a standard MPP challenge from the running middleware, checks the amount/recipient/token/network/body binding, signs once, and retries. It never passes private keys to the LLM or the OpenMCP server. The server loads only its own signing wallet. In this local POC the files share a machine; this is application separation, not an OS security boundary.

Use this prompt once the provider service is running:

> I am looking into acquiring a mid-sized logistics company called FreightFlow. Build a comprehensive due diligence report on operational health, hidden legal liabilities, and competitor market share. Use the active OpenMCP session budget returned by `balance`; do not hardcode 1500 or override it. Include source costs, remaining budget, and both MPP payment receipts for each source. Clearly label fictional demo evidence.

## Rehearse and integrate

```bash
uv run openmcp check-mcp  # Free stdio handshake + discovery; no payments
uv run openmcp demo       # Six real testnet payments against the three paid endpoints
uv run openmcp balance    # Budget, both-hop receipts, and all five on-chain balances
uv run openmcp reset      # New service budget; keeps on-chain funds and payment journals
```

The provider app validates its routes, prices, fee, and public recipients against `catalog/providers.json` at startup. A receiving provider does **not** need its wallet's private key for this MPP charge flow; it uses a separate challenge-signing secret.

The UI integration is [docs/frontend-contract.md](docs/frontend-contract.md). `/dashboard` exposes real testnet balances, both receipt objects, and session earnings. `/events` exposes both challenge/payment sequences for visualization.

## Retry and failure behavior

- Initial unpaid requests return HTTP 402 plus `WWW-Authenticate: Payment …`. No provider data or wallet funds are returned by an unpaid request.
- The amount, chain, token, recipient, request body, and unique memo are bound into the payment. A wrong provider price or address is rejected before signing.
- Each caller persists its signed credential **before** sending it. Retrying the same request/key reuses that credential. A second 402 after signing is an error, never permission to sign another payment.
- A successful incoming payment consumes the service budget even while provider fulfillment is pending. The response includes the incoming receipt where available. A retry resumes the downstream request without charging the agent again.
- Completed executions replay the original data and both receipts. Pending executions block demo reset. Reset changes the spending allowance, not wallet balances or chain history.
- MPP charges here are two separate on-chain operations. They are **not atomic**. If a provider fails after the agent pays, the execution stays pending; this POC does not silently refund, erase a payment, or create a new one. Retry with the same key and resolve any expired or ambiguous payment manually. Challenges expire after five minutes by default, so rehearse recovery promptly.

Run one server worker and one active agent-wallet process for this local, single-agent demo. Multiple wallet processes could contend for transaction nonces. The built-in agent and server serialize each wallet's purchases. Network fees are excluded from the service budget. This POC does not include production custody, automatic refunds, a provider onboarding UI, or multi-tenant provider authentication.

## Verification

```bash
uv run pytest -q
uv run ruff check openmcp openmcp_provider providers traditional_apis demo_runner scripts tests
uv run ruff format --check openmcp openmcp_provider providers traditional_apis demo_runner scripts tests
```

Offline tests use real SDK challenge/credential/receipt handling with a test-only settlement double. They cover both payment hops, retries, malformed terms, budget enforcement, MCP tools, and frontend state.

The opt-in integration test uses the **actual MPP SDK signer and verifier with Tempo testnet**. Its provider is a test-only contract fixture, not your teammate's application. It makes six on-chain payments, verifies the provider balance increases, then replays each purchase without another payment:

```bash
OPENMCP_LIVE_TEST=1 uv run pytest -q -s tests/test_live_mpp.py
```

The receipt evidence is written to `.openmcp/live-proof.json`. The real middleware ledger is isolated from this check. The five wallets are shared, so test payments are visible in their balances.

See [the completed testnet verification](docs/testnet-verification.md) for six transaction links and the exact checks performed.

References: [official Python MPP SDK](https://github.com/tempoxyz/pympp), [MPP specification](https://github.com/tempoxyz/mpp-specs), [Tempo testnet MPP examples](https://github.com/tempoxyz/mpp-irl), and [Claude MCP setup](https://code.claude.com/docs/en/mcp).
