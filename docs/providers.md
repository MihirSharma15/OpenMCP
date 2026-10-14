# Provider onboarding

A provider groups services with published prices, input/output schemas and an
adapter. PostgreSQL is the catalog used by discovery and execution. Source files
are definitions or explicit import/export artifacts, never a startup sync source.

## Publish a built-in integration

Use the target deployment's database, `OPENMCP_PRODUCT_MODE`, and worker environment.
Configure its private API credential using the variable named by `secret_ref`.

```sh
uv run openmcp providers list --builtins
uv run openmcp providers validate tavily
uv run openmcp providers register tavily
uv run openmcp providers list
uv run openmcp providers enable tavily-web-search
uv run openmcp providers disable tavily-web-search
```

`validate` checks the definition and presence of its credential. It makes no vendor
request and cannot prove that a key has valid permissions or quota. `register`
publishes that provider's services disabled by default. Use `--enable` to publish
and enable in one explicit operation. An existing recovery hold remains in place;
resolve its cause and use `providers enable ENDPOINT` to clear that hold. Registration updates matching IDs without
deleting other providers. Disable superseded endpoints explicitly.

These commands do not buy subscriptions, create vendor accounts, or purchase test
results. Credential changes require restarting the worker. Published catalog
changes are read from PostgreSQL without restarting the API or worker.

Account `test` mode is not a universal vendor sandbox. DataForSEO selects its
sandbox in test mode; most integrations still call real APIs and consume quota.
Optional diagnostics are explicit:

```sh
uv run openmcp providers check dataforseo
uv run openmcp providers check tavily --allow-one-credit
```

## Import and export

```sh
uv run openmcp providers export --output /tmp/services.json
uv run openmcp providers import /tmp/services.json
```

An import is a JSON array of providers in the same shape as the export: provider
ID, name, description, optional credential variable name, and `queries` containing
service definitions. Each service has an endpoint ID, schemas, retail price,
mode, adapter and settlement type. Imports default to disabled; use `--enable`
explicitly. They must match the target mode and cannot take another provider's
endpoint ID. Missing files and malformed definitions are errors; an empty import
does not clear the catalog. Exports contain secret variable names, never values.

`OPENMCP_PRODUCT_CATALOG` is retired and ignored. Existing database rows stay in
place when upgrading. Import an existing grouped catalog once if needed, then
remove the variable from deployment configuration. No service is automatically
deleted because a file changes or disappears.

## Add a new adapter

Each built-in integration owns three modules:

- `catalog.py`: `provider(mode)` returns metadata, schemas, bounded prices and credential references.
- `protocol.py`: vendor-specific validation, normalization and billing interpretation.
- `adapter.py`: `validate(service)`, async `prepare(service, payload, key, http, timeout)`, and `parse(service, payload, response, data, context)`.

Add the package name to `integrations/registry.py`. The shared caller owns request
journaling, response limits and capture; adapters own authentication, URL/method,
request shape, output normalization and cost. They return a `transport.Request`
and a `(data, receipt, cost_microusd)` result. Unknown cost is `None`, not an assumed
MPP percentage. `transport.Rejected` is reserved for conclusive zero-cost failures.
A sent request with an uncertain outcome is never automatically repeated.

Add protocol and account-worker tests. No provider-specific SQL allowlist or CLI
registration branch is needed. Existing deployed migrations remain immutable;
apply the current migrations before deploying this registry implementation.

## Creator services

Creator validates the source through a real sample, which may consume quota. Then:

```sh
uv run openmcp creator publish created-JOB_ID
uv run openmcp providers enable created-JOB_ID
```

Publication uses the same account catalog operation. Configure
`OPENMCP_CREATOR_API_TOKEN` on both the Creator host and purchase worker. The
separate admin token authorizes job management. A live account deployment requires
a public HTTPS Creator URL; local HTTP hosting is supported for account test mode.
See [Creator setup](../openmcp_creator/README.md).
