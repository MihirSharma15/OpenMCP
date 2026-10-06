# Running the OpenMCP account MVP

The account product connects Clerk sign-in, Stripe-funded USD credits, capped agent credentials, and outgoing MPP provider payments. Its implementation scope and HTTP interface are recorded in [the tickets](mvp-tickets.md) and [the shared contract](mvp-api-contract.json).

**What the wallet means**

A user's wallet is their prepaid USD credit balance in PostgreSQL. Stripe collects the top-up payment. The platform separately funds a stablecoin treasury to pay registered MPP providers. A user does not need a crypto wallet or private key.

An agent's lifetime allowance is separate from that balance. Adding money or replacing an API credential never increases the allowance. Pending purchases reserve both wallet funds and allowance. A completed purchase captures the retail charge; a terminal failure returns the reservation once. Uncertain settlement remains pending or under review until reconciled.

The account runtime is isolated from the legacy fictional testnet demo. Choose `--mode account` explicitly. Account mode does not use the shared demo token, global session/reset endpoint, or local agent crypto signer.

**Start the account application**

Use separate test and live deployments. Start with non-live integrations and the existing PostgreSQL container. From the repository root:

```bash
uv sync --locked
docker compose up -d postgres
```

Set the account variables from the root `.env.example` in a private environment file or deployment secret store. Set `OPENMCP_PRODUCT_DATABASE_URL=postgresql://openmcp:openmcp@localhost:5433/openmcp` for this local database. Configure Clerk and Stripe test credentials, an approved test service catalog, and an owner-only testnet treasury key. The account runtime does not borrow the demo's wallet files. Do not overwrite existing environment files or commit secrets.

The local website origin is **`http://localhost:3000`**. Use this exact origin for `OPENMCP_PRODUCT_FRONTEND_URL`, `CLERK_AUTHORIZED_PARTIES`, and frontend `OPENMCP_APP_ORIGIN`. The API origin may be `http://127.0.0.1:8000`. Origin mismatches can prevent session validation, checkout return, or CSRF validation.

Apply migrations as a separate deployment step. Normal API/worker startup performs no DDL and runs with a restricted runtime login. Export `OPENMCP_PRODUCT_MIGRATION_DATABASE_URL` only for the migration command if that login differs. Database setup and `database-check` do not require Stripe or Clerk configuration. See [Supabase migration and connection details](supabase-migration.md).

Run these with the same runtime environment after migrations:

```bash
uv run python -m openmcp.product.cli migrate
uv run python -m openmcp.product.cli database-check
uv run openmcp serve --mode account --host 127.0.0.1 --port 8000
```

```bash
uv run python -m openmcp.product.cli worker
```

The worker processes both durable Stripe events and purchases. At most one worker per account schema obtains the treasury lock. Store the treasury private key only on the worker host (Render); the account API (Vercel) and frontend do not need `OPENMCP_TREASURY_KEY_FILE` or the key file. Both the API and worker still validate the same mode, chain, token, and approved service catalog. The treasury key must belong exclusively to this deployment; sharing a signer between independent schemas or external senders would invalidate the single nonce-stream assumption. The API refuses new purchases when the worker heartbeat is stale.

In `frontend/`, configure the variables in `.env.example`, install dependencies, and start Next.js:

```bash
npm install
npm run dev
```

Open `http://localhost:3000/dashboard`. The required Clerk setup follows [Clerk's skill](https://clerk.com/SKILL.md): run `npx -y clerk@latest init` and `npx -y clerk@latest doctor` where network access is available. Accountless development configuration does not provision or claim a production Clerk account. Install the real `@clerk/nextjs` dependency before building; no compatibility stubs are provided.

The frontend uses Clerk sign-in/sign-up and sends session tokens through a narrow same-origin API proxy. FastAPI verifies the configured issuer, RS256 signature, expiry and authorized party. Clerk user IDs are namespaced by issuer. Browser and agent credentials have separate permissions.

**Configure funding and services**

Stripe Checkout collects payment details on Stripe. Enable Link in the Stripe account's payment-method settings; availability follows Stripe's dynamic payment-method rules. Create the webhook endpoint at `https://YOUR_API_ORIGIN/v1/webhooks/stripe` and subscribe to the events listed in the root `.env.example`. For local testing, forward Stripe test events to that same route with the Stripe CLI and configure the forwarding endpoint's signing secret. Credit is created only after verified Stripe reconciliation, never from the browser's success or cancellation query. See [Stripe's Checkout fulfillment contract](https://docs.stripe.com/checkout/fulfillment) and [Link in Checkout](https://docs.stripe.com/payments/link/checkout-link).

`OPENMCP_PRODUCT_CATALOG` optionally points to a JSON array of approved providers. For a new installation with no providers, leave it unset (remove the variable rather than supplying an empty string). An unset variable preserves any catalog already stored in the database. A configured file that is missing logs a warning and supplies an empty catalog, just like a file containing `[]`; startup clears the stored provider catalog in either case. Existing purchase records remain intact. Invalid JSON and permission errors still fail startup. With no providers stored, discovery returns an empty list and execution rejects unknown services without reserving credits. The worker still processes Stripe events without a treasury signer when there are no enabled MPP services or unfinished MPP payments. Once an MPP service is added, configure its funded signer and restart the worker. Removing a provider never removes the signer requirement for its unfinished payments.

Each provider has `provider_id`, `name`, `description`, and `queries`. There is no user-submitted URL or self-service provider onboarding in this iteration. A flat array of services is still accepted: each service is stored as its own provider, using that service's endpoint id, name, and description. Discovery matches the caller's words against provider and query names and descriptions. Keywords are stored with the query and are not search terms. A disabled example:

```json
[
  {
    "provider_id": "approved-provider",
    "name": "Approved provider",
    "description": "Who publishes these queries and what they cover.",
    "queries": [
      {
        "endpoint_id": "approved-service",
        "name": "Approved service",
        "description": "Describe the real result and when an LLM should buy it.",
        "keywords": ["research"],
        "url": "https://YOUR_PROVIDER_ORIGIN/paid-tool",
        "recipient": "0x0000000000000000000000000000000000000000",
        "settlement": "mpp",
        "price_cents": 40,
        "input_schema": {
          "type": "object",
          "properties": {"query": {"type": "string"}},
          "required": ["query"],
          "additionalProperties": false
        },
        "output_schema": {
          "type": "object",
          "properties": {"answer": {"type": "string"}},
          "required": ["answer"],
          "additionalProperties": false
        },
        "enabled": false,
        "mode": "test",
        "supports_idempotency": true
      }
    ]
  },
  {
    "provider_id": "approved-api",
    "name": "Approved API provider",
    "description": "Who publishes this HTTP API and what it returns.",
    "secret_ref": "APPROVED_API_KEY",
    "queries": [
      {
        "endpoint_id": "approved-api-search",
        "name": "Approved API search",
        "description": "Describe the real result and when an LLM should buy it.",
        "keywords": ["search"],
        "url": "https://YOUR_PROVIDER_ORIGIN/search",
        "settlement": "api_key",
        "price_cents": 40,
        "input_schema": {
          "type": "object",
          "properties": {"query": {"type": "string"}},
          "required": ["query"],
          "additionalProperties": false
        },
        "output_schema": {"type": "object"},
        "enabled": false,
        "mode": "test",
        "supports_idempotency": true
      }
    ]
  }
]
```

`settlement` defaults to `mpp`. An MPP query needs the provider's Tempo recipient. An `api_key` query does not: its provider sets `secret_ref` to an environment variable name, and that variable holds the bearer token. The catalog file never contains the token. The name is stored on the provider row only and is not copied onto purchases or discovery responses. The worker reads the variable when it POSTs. Private, link-local, and non-test localhost URLs are rejected. Hostnames are not resolved; DNS rebinding is out of scope. Test mode may use a loopback URL for a local adapter.

Replace every placeholder and confirm the provider's replay behavior before enabling it. At a 40-cent retail price, an MPP challenge must request 36 cents. It must bind the body digest and execution memo, accept the forwarded execution/idempotency ID, and replay the same paid credential's receipt and result. The existing provider package demonstrates that protocol; its fictional demo services do not constitute a live provider. An API-key query charges the same retail price and does not add a second vendor fee. Restart the API and worker after catalog changes. Startup copies the file into the account database and drops catalog rows that are no longer listed. Purchases keep the terms saved on the execution. The worker checks current catalog terms before signing an MPP payment and retains immutable terms for already signed payments.

Test configuration defaults to Tempo testnet. Live mode requires explicit production settings and the supported mainnet USDC address; providers can be added later. MPP settlement additionally requires an enabled HTTPS live provider and a private treasury key; see the root `.env.example` and [Tempo's SDK network/token definitions](https://github.com/tempoxyz/pympp/blob/main/src/mpp/methods/tempo/_defaults.py). Configure the signer as either a raw private hex key or JSON containing `private_key`, in an owner-only regular file (`chmod 600`). Never pass the key through the browser, account API, MCP client, or command arguments.

**Connect an LLM**

Create a named agent in `/dashboard/agents`, choose its lifetime allowance and expiry, and issue a credential. The credential is displayed once. From the OpenMCP runtime directory, use the hidden prompt:

```bash
uv run openmcp connect --base-url https://YOUR_API_ORIGIN
uv run openmcp install all --mode account --scope user --dry-run
uv run openmcp install all --mode account --scope user
uv run openmcp check-mcp --mode account
```

For local development the origin can be `http://127.0.0.1:8000`. External origins require HTTPS. Replace `all` with `codex`, `claude-code`, or `cursor` to select a client. If an existing OpenMCP entry uses demo mode, review the proposed change and add `--replace` when applying the account configuration. Unrelated client settings and tool restrictions are preserved.

`connect` saves the credential with mode 600 under `.openmcp/account-client/agent-token`; the containing directory is private. Configuration and purchase retries use that same runtime directory even when the client opens a different project. Do not paste a credential into a command argument, skill, chat message, or checked-in client configuration.

Restart the MCP client after installing. The free connection check calls balance and discovery; it does not purchase a service. For other clients, export a configuration fragment with:

```bash
uv run openmcp mcp-config --mode account --format json
```

Account tools are `balance`, `discover`, `execute`, and `execution_status`. The purchasing skill explains budgets, evidence handling, and refunds. `execute` requires an endpoint ID, payload, maximum approved price in cents, and an idempotency key. Reuse identical arguments/key after a lost response. A status lookup can use the execution ID or the original key; it never initiates a payment. `submission_unknown` means the client did not receive an execution ID, so recover by retrying the original purchase arguments/key.

**Local client configuration**

| Variable | Purpose |
| --- | --- |
| `OPENMCP_MODE` | Optional CLI default: `account` or `demo`; exported account server entries pin their mode explicitly |
| `OPENMCP_ACCOUNT_STATE` | Private client state directory; default `.openmcp/account-client` |
| `OPENMCP_ACCOUNT_BASE_URL` | Explicit API origin; changing the origin saved by `connect` requires reconnecting |
| `OPENMCP_AGENT_TOKEN_FILE` | Optional existing private credential file for an explicitly configured connection |

Purchase arguments are journaled privately before the client sends the HTTP request. The gateway's idempotency record is authoritative for payment. Reinstalling a client or switching credentials does not grant permission to repeat an uncertain purchase under a new key.

**Configuration needed before a live pilot**

The frontend needs a claimed Clerk application and the account backend's fixed API origin. The backend needs a PostgreSQL connection, trusted Clerk issuer and permitted frontend origins, Stripe keys and a signed-event endpoint, an enabled service catalog, and a separately funded mainnet treasury. Provider URLs and receiving wallets are operator configuration; the model cannot supply them.

Test and live environments must use separate credentials and data. On first startup, the database schema is bound to its mode, chain and token; changing these requires a separate schema. The worker also binds its treasury address. A real-money proof requires the configured live service, funded treasury, and an explicitly specified test spending limit. Automated tests with simulated settlement do not establish that live payments have been exercised.

Never expose the legacy demo runner, operator token, or reset endpoints as live account APIs. The user dashboard communicates only with the account application's `/v1` routes. Ledger mutations and discretionary reconciliation are internal/operator operations, not MCP tools.

**Operate and recover**

`GET /health/live` checks the API process. `GET /health/ready` checks persistence and the worker heartbeat. Run the operator checks in the backend environment:

```bash
uv run python -m openmcp.product.cli doctor
uv run python -m openmcp.product.cli doctor --chain
uv run python -m openmcp.product.cli review
```

The chain check validates the configured network and token decimals and reports the public treasury address and liquidity; it does not send money. `doctor` reports worker liveness, review counts and Stripe backlog/retries. `review` lists up to 100 unresolved executions and pending Stripe events without exposing signed credentials or provider payloads. A low treasury balance returns the customer reservation without claiming that Stripe funds were converted to crypto.

An uncertain purchase keeps its reservation. After bounded automatic retries, it is marked `needs_review`. To reconcile an execution, stop the active worker, then use the restricted CLI with the execution ID shown in the transaction detail:

```bash
uv run python -m openmcp.product.cli reconcile --execution-id exe_REPLACE
```

This reuses the saved signed credential. It must not generate a new purchase or idempotency key. After a proven fulfillment failure, the operator may run:

```bash
uv run python -m openmcp.product.cli reconcile --execution-id exe_REPLACE --refund --reason 'Confirmed service failure'
```

Refunding an unresolved signed transfer is rejected. If payment succeeded but fulfillment failed, the platform absorbs the provider cost. Restart the worker after the command. Keep access to the CLI, database and signer limited to operators; there is no browser admin debit/refund endpoint.

Funding reversals are separate from service refunds. Stripe events record deposit adjustments and any resulting deficit. Top-ups can cover a deficit, but an open dispute can continue to restrict purchases. Respond to a dispute in Stripe; do not reset balances or delete ledger rows.

Back up PostgreSQL with encrypted, access-controlled backups and test restoration into an isolated database. Synthetic/test backups can run recovery with `OPENMCP_PRODUCT_MODE=test`. A production backup retains its immutable live-mode binding: inspect it without a signer or external worker, and never change that binding to make it a test database. Signed credentials in execution records are sensitive. Back up signer material separately under equivalent access controls. Before an upgrade or restoration, stop the API and worker, preserve the current database and signer, restore with PostgreSQL's normal `pg_dump`/`pg_restore` procedure, and run migration and doctor. Never attach a restored historical database to a live signer and resume new spending before reconciling every pending/signed execution against Stripe and chain state. Test a restart with pending work and a synthetic restore before allowing real money.

**Validate the implementation**

```bash
OPENMCP_REQUIRE_POSTGRES=1 uv run pytest tests/test_product_postgres.py -q
OPENMCP_REQUIRE_POSTGRES=1 OPENMCP_TEST_RESTORE=1 uv run pytest tests/test_product_restore.py -q
uv run pytest -q
```

The database checks must have `OPENMCP_PRODUCT_DATABASE_URL` configured and fail if the database cannot be reached. Use `OPENMCP_DATABASE_PROVIDER=postgres` when overriding a Supabase workspace configuration with local PostgreSQL. The restore check requires CREATEDB only on its restore target and PostgreSQL client tools or the local Compose PostgreSQL service. For a hosted source, set `OPENMCP_TEST_RESTORE_TARGET_DATABASE_URL` to an isolated local database and follow [the Supabase verification procedure](supabase-migration.md). It uses synthetic funds in a unique schema, restores to a fresh temporary database, runs recovery in a new Python process, verifies the source stayed unchanged, and removes its test databases. It never contacts Stripe or signs a real payment. `.github/workflows/account-mvp.yml` provisions PostgreSQL 16 and 17 and requires the accounting suite. In `frontend/`, run `npm test`, `npm run build`, and `npm run typecheck` after installing Clerk. A passing isolated unit suite is not a substitute for PostgreSQL concurrency, browser integration, restore, or bounded live-payment acceptance.
