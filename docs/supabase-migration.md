# OpenMCP Supabase migration

Implemented October 5, 2026 for the account product. The connected project is `juzkcryuajhmawqhzwtm` (`OpenMCPProject`), database `postgres`, PostgreSQL 17.11. The private `openmcp_product` schema now holds the ten account tables plus a schema compatibility record. The workspace backend uses a dedicated `openmcp_app` login through the session pooler with certificate and hostname verification.

`DatabaseManager` now owns bounded pooling, transaction scopes, schema selection, timeouts, readiness checks and shutdown. The existing `Store` is the SQL repository and accepts an injected manager. API and worker startup check the schema instead of applying DDL. Settlement receives a `WorkerLease`, which checks that its original database session still holds the advisory lock before signing or sending.

The account API, wallet, history, Stripe event handling, purchases and refunds all use this database boundary. Clerk remains the identity provider. Stripe and outgoing MPP behavior are unchanged. The separate demo, Creator, provider SDK and local MCP recovery journal retain their existing stores; those are outside this account migration.

This provisions the database and configures the local backend. It does not deploy the API/worker or activate live payments. The current local product mode remains `test`; the main account schema starts empty. Synthetic acceptance uses temporary schemas that are removed afterward. No customer records existed in the inspected source account database.

## Applied changes

- `openmcp/database.py`: pooled transactions and dedicated worker leases. Direct/session connections only; port 6543 is rejected. Supabase requires `sslmode=verify-full`.
- `openmcp/product/store.py`: all existing accounting operations use the injected manager; their row locks, idempotency constraints and terminal guards remain in place.
- `openmcp/product/app.py` and `cli.py`: shared manager construction, explicit migrations, readiness checks and resource cleanup. `database-check` runs before Clerk/Stripe setup is complete.
- `supabase/migrations/`: authoritative baseline and indexes. The Python wheel bundles these exact files; the previous duplicate baseline is removed. Filenames match the remote Supabase migration history.
- Private schema, RLS and an environment-specific NOLOGIN privilege role. `openmcp_app` can read/insert/update accounting rows and delete expired rate-limit records; it cannot create schema objects, delete ledger rows, alter the schema version, create roles/databases or bypass RLS.
- No schema/table/sequence grants to `PUBLIC`, `anon`, `authenticated` or `service_role`. Per-account ownership still belongs to the trusted backend repository, not a browser-supplied database context.
- Legacy credit adapters now read `OPENMCP_LEGACY_DATABASE_URL`; they cannot accidentally inherit the account DSN.

## Connection and operation

The observed session endpoint is `aws-0-us-east-1.pooler.supabase.com:5432`. A runtime username uses the form `openmcp_app.PROJECT_REF`. The project allows 15 server connections per user/database and 200 client connections. Local configuration uses a pool maximum of 2 per process, plus one dedicated session per worker. Budget replicas accordingly.

The ignored root `.env` contains only the runtime DSN. The migration credential and generated runtime credential were saved separately in owner-only files under ignored `.openmcp/`; never copy the migration credential into API/worker hosting secrets. Download the project's CA from Database Settings and set its path through `sslrootcert`. [Supabase TLS documentation](https://supabase.com/docs/guides/platform/ssl-enforcement).

```bash
uv sync --locked
uv run python -m openmcp.product.cli database-check
```

For a fresh deployment, export `OPENMCP_PRODUCT_MIGRATION_DATABASE_URL` only to the explicit migration command. Migrations need database configuration only; Clerk, Stripe and a signer are not prerequisites. Use a migration identity that can create roles and objects, then grant the schema's `SCHEMA_runtime` role to a separate runtime login. Passwords are provisioned privately, never in SQL migration files.

```bash
uv run python -m openmcp.product.cli migrate
```

The connected project already has both migrations. New remote changes should go through the Supabase migration workflow; normal startup will not repair a missing or incompatible schema. Startup binds the schema permanently to its payment mode/network/token, and the worker binds its signer. Use an independent schema and runtime role, preferably a separate project, for live funds.

## Verification

Completed October 5, 2026:

- Full local regression on PostgreSQL 16: **266 passed**, one optional live-payment test skipped.
- PostgreSQL 17 account, boundary and recovery suite: **20 passed**.
- Supabase PostgreSQL 17.11 with the restricted runtime login: **11 accounting/API tests and 8 boundary tests passed**. The HTTP journey was rerun after extending its synthetic token's lifetime for remote round trips.
- Supabase `pg_dump` → separate local PostgreSQL 17 → fresh-process recovery: **passed**. The hosted runtime has no CREATEDB privilege.
- All 11 private tables have RLS enabled; browser/Data API roles have no schema access. Security advisor: **no findings**. Remaining performance notices only identify unused indexes in the empty account schema.
- Migration history matches both committed SQL filenames. Wheel build contains both authoritative migrations. Lint, whitespace and Git-visible secret checks pass.

Tests use synthetic identities, Stripe responses and provider results. They make no external charge or transfer. Account money is tested with the real repository, routes, webhook verification, worker and PostgreSQL transactions.

Local acceptance covers concurrency, deposits/reversals, spending caps, duplicate requests, refunds, ownership, revocation, expired grants, mode/signer binding and worker exclusion. Boundary tests additionally cover rollback, transaction-local settings, lost/unlocked worker sessions, least privilege, missing schema detection, legacy isolation, and API startup/shutdown without DDL. CI runs PostgreSQL 16 and 17.

For Supabase acceptance, give the runner a privileged test setup DSN in `OPENMCP_PRODUCT_DATABASE_URL` and the separate restricted login in `OPENMCP_TEST_RUNTIME_DATABASE_URL`, with `OPENMCP_DATABASE_PROVIDER=supabase`. Run only the account integration files. Each fixture creates an isolated `product_test_*` schema, grants its private role to the runtime login, runs assertions, then removes the schema and role. Do not point a full legacy/demo suite at a production database.

```bash
OPENMCP_REQUIRE_POSTGRES=1 uv run pytest tests/test_product_postgres.py tests/test_product_database.py -q
```

The optional restore test accepts `OPENMCP_TEST_RESTORE_TARGET_DATABASE_URL` so a Supabase source can be restored into an isolated local PostgreSQL 17 instance. Only the local restore identity needs CREATEDB. With no local PostgreSQL client installed, `OPENMCP_TEST_POSTGRES_CLIENT_CONTAINER` can name a dedicated `openmcp-verification-*` container containing matching client tools. Copy the public CA certificate to `/tmp/supabase-ca.crt` there. Credentials pass through environment variables, not CLI arguments. Set `OPENMCP_TEST_RESTORE=1` and run `tests/test_product_restore.py`; it backs up only its own temporary schema and verifies pending signed/reserved work in a fresh process.

A successful database check reports a connection and schema compatibility, not worker readiness. Until a payment worker is configured and running, `worker` correctly reports `false`.

## Scope and ticket status

| Ticket | Delivered |
| --- | --- |
| SB-01 Database boundary | Injected manager, existing SQL repository, dedicated worker lease, API/CLI wiring and cleanup. |
| SB-02 Connection isolation | Bounded pool, TLS verification, timeouts, transaction-local schema, restricted login, rejection of transaction-pooler port, separate legacy DSN. |
| SB-03 Supabase migrations | Versioned authoritative baseline and indexes, private grants/RLS, separate migration command, schema readiness without runtime DDL. |
| SB-04 Local compatibility | Accounting, concurrency, rollback, lease, permissions, lifecycle and restore tests; PostgreSQL 16/17 CI matrix. |
| SB-05 Hosted acceptance | Real Supabase connection with separate runtime login; synthetic accounting and boundary acceptance; remote grants/RLS/advisor checks. |
| SB-06 Cutover/operations | Empty account schema provisioned and local backend connected; deployment of hosted API/worker processes remains separate. |
| SB-07 Other server stores | Outside this iteration: Creator jobs, provider SDK replay/fulfillment, and the legacy demo retain their stores. |

The local MCP request journal remains local because it must persist intended requests even when the backend cannot be reached. Customers never receive platform database credentials. No demo balances were imported as customer funds.

## Rollout and rollback

No customer account data existed in the inspected local or hosted databases, so this cutover creates an empty account schema. If migrating another populated deployment later, stop new purchases/top-up creation and the signer, preserve a consistent backup, account for incoming Stripe events, and move all accounting tables together. Preserve IDs, idempotency keys, signed payment evidence, pending reservations and transaction sequence values. Reconcile balances, allowances and external payment outcomes before resuming.

Never run the same signer against two independent databases: their advisory locks cannot coordinate. Never dual-write money records. Before new writes, rollback can restore the old connection settings. After new writes, stop payments and reconcile/reverse-migrate new records before reverting; a stale database would lose charges and replay protection.

## Deployment still required

Configure the runtime DSN and CA certificate in the API and worker hosts. Place both services near the database's `us-east-1` region to reduce query latency. Complete backend Clerk issuer/origins, Stripe keys and signed webhook configuration, approved providers, and the separately funded treasury before running payments. The Supabase connector provisions and inspects the database; it does not host FastAPI or the payment worker.

Use a dedicated live deployment with its own data and runtime login. Synthetic Stripe/provider tests establish database accounting behavior; they do not prove a real charge, refund or mainnet transfer. Production backup retention and an operator recovery schedule still need to be configured for the chosen hosting plan.
