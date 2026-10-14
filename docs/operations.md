# Account operations

The account API verifies Clerk sessions, manages capped agent credentials, and
reserves USD credits. A continuously running worker processes durable Stripe
events and provider executions. Both use the same PostgreSQL schema and mode.

## Configuration and startup

Copy placeholders from the root `.env.example` into private configuration. Use
separate test/live databases, Stripe credentials and Clerk applications. Keep the
website origin identical in Clerk authorized parties, frontend
`OPENMCP_APP_ORIGIN`, and backend `OPENMCP_PRODUCT_FRONTEND_URL`.

```sh
uv sync --locked
docker compose up -d postgres
uv run openmcp migrate
uv run openmcp database-check
uv run openmcp serve --host 127.0.0.1 --port 8000
```

Start `uv run openmcp worker` in another process. Apply migrations explicitly with
the privileged deployment connection; API/worker startup performs no DDL. Set
`OPENMCP_PRODUCT_MIGRATION_DATABASE_URL` only for the migration command when that
connection differs from the restricted runtime role. See [database setup](supabase-migration.md).

The Vercel entrypoint is `openmcp.product.vercel:app`. It hosts the API, not the
worker. Readiness requires PostgreSQL and a recent worker heartbeat. One worker
per schema holds the database lease; extra workers wait instead of duplicating calls.

Configure the frontend using `frontend/.env.example`, then run `npm ci` and
`npm run dev` in `frontend/`. The dashboard is at `http://localhost:3000/dashboard`.
The same-origin frontend proxy forwards Clerk sessions for independent API
verification. Human sessions and agent credentials have distinct permissions.

## Funding and purchases

Stripe Checkout creates account credits only after verified server-side
reconciliation. The browser return URL cannot credit a wallet. Configure a Stripe
webhook at `/v1/webhooks/stripe` using the event list in `.env.example`; local Stripe
forwarding must use its own webhook signing secret.

Wallet funds and agent lifetime allowances are separate. Both reserve capacity
for pending purchases. Successful fulfillment captures the retail charge once.
Conclusive failures before sending release the reservation; uncertain sends or
payments remain under review. A service credit refund does not reverse a vendor
charge. Stripe funding reversals and disputes are separate ledger events and may
restrict the account.

Follow [provider onboarding](providers.md) to publish services. Startup never
changes the catalog. Never reuse a new purchase key to recover a lost response;
retry the original request/key or poll its execution ID.

## Recovery

```sh
uv run openmcp doctor
uv run openmcp review
uv run openmcp reconcile --execution-id exe_ID
```

Stop the active worker before discretionary reconciliation. An operator may return
credits with `--refund --reason 'verified reason'` after establishing the outcome.
An already-sent API-key request is not automatically sent again. A confirmed
payment with failed fulfillment may disable the service pending operator review.
Use `openmcp providers enable ENDPOINT` only after resolving that failure.

Outgoing MPP purchases remain supported for registered MPP providers. Their worker
requires an exclusively owned, separately funded treasury key stored in an
owner-only file. The API and frontend never need this key. In live mode the
approved chain/token are Tempo mainnet USDC; test mode uses Moderato. Customer
Stripe proceeds do not automatically fund the treasury. API-key providers and
Creator need no signer, unless unfinished MPP purchases still require recovery.

## Upgrading from the retired demo

Apply all migrations, including `20261013000000_provider_registry.sql`, before
restarting API and worker. It removes provider-specific database allowlists and
records unknown upstream costs as unknown. Account records and purchase snapshots
are preserved. Remove `OPENMCP_PRODUCT_CATALOG`; existing published rows remain.

`openmcp serve`, `mcp`, and installation now select accounts by default. Existing
`--mode account` commands remain accepted. Replace old client configurations with
`openmcp install ... --replace` after reviewing their diff. The shared-wallet demo
commands and old credit routes are removed. Files under `.openmcp/` are left intact;
Creator now uses its own `.openmcp/creator/jobs.sqlite3` and requires new jobs and
sample validation before publication. Retired demo registrations are not imported.
