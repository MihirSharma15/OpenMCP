# OpenMCP

OpenMCP lets AI agents discover and buy registered API services using prepaid USD
credits and an owner-issued spending allowance. API Creator turns researched
sources into validated services that publish into the same catalog.

```text
Human → Next.js / Clerk → account API ← local MCP tools ← AI agent
                              ↕
                         PostgreSQL
                              ↕
                       purchase worker → external APIs
                                       → Creator service host
```

Stripe Checkout funds the account ledger. Purchases reserve both credits and agent
allowance before the worker calls a provider. Successful results and receipts are
saved before the retail charge is captured. Uncertain calls remain under review;
retrying a purchase uses its original idempotency key.

## Run locally

Requires Python 3.11+, uv, Node.js, and PostgreSQL. Configure private variables from
[.env.example](.env.example) and [frontend/.env.example](frontend/.env.example).
Clerk and Stripe test credentials are needed for the account website.

```sh
uv sync --locked
docker compose up -d postgres
uv run openmcp migrate
uv run openmcp database-check
uv run openmcp serve
```

Run the worker separately with the same database and mode:

```sh
uv run openmcp worker
```

Then run `npm ci` and `npm run dev` in `frontend/`. Open
`http://localhost:3000/dashboard`, add credits, create an agent allowance and issue
a credential. Connect an MCP client using the hidden credential prompt:

```sh
uv run openmcp connect --base-url http://127.0.0.1:8000
uv run openmcp install all --scope user
uv run openmcp check-mcp
```

Accounts are the default and only client mode. MCP tools are `balance`, `discover`,
`execute`, and `execution_status`.

## Add services

Provider definitions live alongside their adapters in `openmcp/integrations/`.
PostgreSQL holds the published catalog. API and worker startup never import,
replace, or prune provider records.

```sh
uv run openmcp providers list --builtins
uv run openmcp providers validate tavily
uv run openmcp providers register tavily
uv run openmcp providers enable tavily-web-search
```

Registration creates disabled services unless `--enable` is supplied. Validation
checks definitions and credential configuration without contacting the vendor.
See [provider onboarding](docs/providers.md) for imports, exports, credentials,
adapter development, and service lifecycle.

[API Creator](openmcp_creator/README.md) researches sources, validates an upstream
sample, and waits for explicit publication. Generated endpoints are authenticated
HTTP services called by the account worker; no local crypto wallets are needed.
Creator remains a local, single-operator process with durable job checkpoints.

## Code map

| Location | Responsibility |
| --- | --- |
| `openmcp/product/` | Account HTTP API, Stripe funding, credit ledger, purchase worker and reconciliation |
| `openmcp/account_client.py`, `account_mcp.py`, `client_setup/` | Account MCP client and installation |
| `openmcp/providers.py`, `integrations/` | Explicit catalog publication and provider adapters |
| `openmcp_creator/` | Browser research, credential vault, sample validation and generated-service hosting |
| `frontend/` | Sign-in, balances, agents, transactions and marketing website |
| `supabase/migrations/` | Deployed PostgreSQL migration history |
| `tests/` | Provider protocols, accounting, recovery, Creator and client checks |

## Operations and verification

- [Account operations](docs/operations.md)
- [HTTP contract](docs/api-contract.json)
- [Database setup and migration](docs/supabase-migration.md)
- [Client installation](docs/clients.md)

```sh
uv run pytest -q
uv run ruff check openmcp openmcp_creator tests
uv run ruff format --check openmcp openmcp_creator tests
cd frontend
npm test
npm run build
npm run typecheck
```

Database tests create isolated schemas. CI requires PostgreSQL; set
`OPENMCP_REQUIRE_POSTGRES=1` locally to fail instead of skipping database tests.
Tests use simulated vendor/payment responses and do not make paid purchases.

The old shared-wallet demo, fictional providers, earlier account implementation,
and unused AgentCard integration have been retired. Existing local state files
are not erased. The account worker retains outgoing MPP support and recovery for
registered MPP services; API-key providers and Creator do not need that signer.
