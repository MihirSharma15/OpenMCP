# BuiltWith

Two free vendor routes are wired into the account-mode discover → execute → worker flow:

- `builtwith-domain-summary`: one lowercase domain; technology category/group counts, not individual technology names. Subdomains may resolve to a root domain. Index dates are preserved in milliseconds as returned by the live API, rather than interpreting the documentation's seconds examples.
- `builtwith-technology-trends`: one technology name, with spaces replaced by hyphens (for example `Google-Analytics`); metadata and adoption coverage counts, not a historical time series or a list of websites.

Both charge 2 USD credit cents per successful OpenMCP request. Vendor cost is zero for these free routes; the entire retail charge is the OpenMCP service fee. Detailed paid domain lookups, lists, batches, relationship queries and change queries are not supported.

The operator confirmed this provider may be used through OpenMCP. BuiltWith's published terms restrict reselling data as-is or duplicating its functionality; keep any applicable commercial permission with your provider onboarding records. An API key alone is not evidence of a resale agreement.

## Setup

Set `BUILTWITH_API_KEY` in the private worker environment. Never put its value in the catalog. The adapter uses the free API's documented query-key authentication on the outgoing HTTPS request only. The shared caller strips query strings from HTTPX request logs, including the private key. External monitoring must also redact request query strings.

Apply the new `20261007060000_builtwith.sql` migration using your existing privileged migration process. Do not edit already deployed migrations. Then register the provider using the target database URL and account mode:

```sh
uv run openmcp builtwith register
```

This upserts BuiltWith without deleting other providers. For file-catalog setups:

```sh
uv run openmcp builtwith catalog --output catalog/builtwith.json --mode test
```

The committed catalog is test-mode; production registration uses your configured product mode. Deploy the updated API/worker and configure the worker key separately. Catalog files alone do not register production database services.

## Limits and recovery

Only two fixed HTTPS routes are accepted. Inputs cannot supply a target URL, key, arbitrary query parameters or a batch. Redirects are not followed. Responses are bounded to 1 MB and validated before capture. HTTP/vendor errors or malformed results after sending go through the existing API-key review-hold flow (the sent-state policy does not automatically disable the service); retries never submit an already-sent request again. Confirmed results can recover without another vendor call.

Requests are serialized and spaced at least one second apart within an ApiKeyCaller. This assumes the existing single-worker deployment; multiple workers sharing a key would need shared throttling. Free API limit: one request per second.

## Verification

Automated tests mock BuiltWith and exercise PostgreSQL account reservations, worker capture, idempotency replay and saved-result recovery, plus input/response validation, errors and rate spacing. No automated test spends vendor credits.

Two manual vendor calls returned HTTP 200: a free summary of `builtwith.com` and free adoption statistics for `Shopify`. Their actual responses passed adapter validation. These checks did not exercise deployed production billing or the hosted worker. No paid endpoints were called.

Sources: [Free API](https://api.builtwith.com/free-api), [Trends API](https://api.builtwith.com/trends-api).
