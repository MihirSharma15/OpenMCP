# PostgreSQL and Supabase operations

`openmcp/database.py` owns bounded pooling, transaction scopes, schema selection,
timeouts and worker leases. `openmcp/product/store.py` owns account SQL operations.
API and worker startup check schema compatibility and never apply DDL or import a
catalog. Monetary records and registered providers live in the private account
schema; Creator's job journal and the MCP client's request journal remain local.

## Connections and privileges

Use a direct or session-pooled PostgreSQL connection. Port 6543 is rejected because
workers hold session-level advisory locks. Supabase connections require
`sslmode=verify-full` and the project's public CA via `sslrootcert`. Set
`OPENMCP_DATABASE_PROVIDER=supabase` and copy the connection details from your
project's Connect dialog. Do not assume a hostname or connection limit from another
project. [Supabase TLS documentation](https://supabase.com/docs/guides/platform/ssl-enforcement).

Set `OPENMCP_PRODUCT_DATABASE_URL` to a dedicated runtime login. Migrations create
an environment-specific `SCHEMA_runtime` NOLOGIN role; grant it to that login using
the privileged database identity. Runtime roles can read/insert/update operational
records but cannot alter schema, delete ledger rows, create roles/databases or
bypass RLS. Browser/Data API roles receive no schema access. Per-account ownership
is enforced by the trusted backend repository.

Pools default to four connections per process, plus a dedicated worker session.
Budget API replicas and workers against the project's connection limits. A worker
checks that its original database session still owns the lock before signing or
sending money.

## Migrations and upgrades

`supabase/migrations/` contains the authoritative migration history, bundled unchanged
into Python wheels. Apply all unapplied files with the normal Supabase deployment
workflow. For a local database or operator-managed deployment:

```bash
uv run openmcp migrate
uv run openmcp database-check
```

Supply `OPENMCP_PRODUCT_MIGRATION_DATABASE_URL` only to the migration command.
It falls back to the configured database URL for local development. Clerk, Stripe
and a signer are not required to migrate. The operator command replays idempotent
SQL in one transaction; only the final adapter constraint is applied so existing
newer services survive replay. Supabase tracks the original files independently.

The current application requires schema version **2**, introduced by
`20261013000000_provider_registry.sql`. This replaces per-provider SQL allowlists
with a syntactic adapter check and allows unknown provider cost to remain null.
Python's adapter registry still rejects unsupported adapters. Deploy the migration
before starting this version of the API or worker. A code checkout alone does not
upgrade any database.

Startup binds the schema to its payment mode/network/token; the MPP worker also
binds its signer when used. Use independent schemas and runtime roles, preferably
separate projects, for test and live funds. Back up before a production migration.

## Verification and restore

Tests use temporary `product_test_*` schemas, synthetic identities and mocked
external payments/providers. They exercise real PostgreSQL accounting, concurrency,
refunds, ownership, schema checks and worker exclusion. CI covers PostgreSQL 16/17.

```bash
docker compose up -d postgres
OPENMCP_REQUIRE_POSTGRES=1 uv run pytest -q
```

For restricted-role acceptance against a dedicated test project, provide the
privileged setup DSN as `OPENMCP_PRODUCT_DATABASE_URL`, the restricted login as
`OPENMCP_TEST_RUNTIME_DATABASE_URL`, and `OPENMCP_DATABASE_PROVIDER=supabase`.
Run `tests/test_product_postgres.py` and `tests/test_product_database.py`. Fixtures
remove only their temporary schemas and roles.

The opt-in `tests/test_product_restore.py` performs a backup/restore and verifies
reserved/signed work in a fresh process. Set `OPENMCP_TEST_RESTORE=1` and an isolated
`OPENMCP_TEST_RESTORE_TARGET_DATABASE_URL`; the target login needs CREATEDB.
`OPENMCP_TEST_POSTGRES_CLIENT_CONTAINER` can select a dedicated container with
matching PostgreSQL client tools. Keep credentials in private environment variables.

A successful `database-check` verifies connectivity and schema compatibility. It
does not prove that the API, worker, Clerk, Stripe or vendors are configured or
running. See [account operations](operations.md) for those checks.
