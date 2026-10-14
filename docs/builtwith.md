# BuiltWith

Two free vendor routes are wired into the account-mode discover → execute → worker flow:

- `builtwith-domain-summary`: one lowercase domain; technology category/group counts, not individual technology names. Subdomains may resolve to a root domain. Index dates are preserved in milliseconds as returned by the live API, rather than interpreting the documentation's seconds examples.
- `builtwith-technology-trends`: one technology name, with spaces replaced by hyphens (for example `Google-Analytics`); metadata and adoption coverage counts, not a historical time series or a list of websites.

Both charge 2 USD credit cents per successful OpenMCP request. Vendor cost is zero for these free routes; the entire retail charge is the OpenMCP service fee. Detailed paid domain lookups, lists, batches, relationship queries and change queries are not supported.

The operator confirmed this provider may be used through OpenMCP. BuiltWith's published terms restrict reselling data as-is or duplicating its functionality; keep any applicable commercial permission with your provider onboarding records. An API key alone is not evidence of a resale agreement.

## Setup

Set `BUILTWITH_API_KEY` in the private worker environment. The database stores only the variable name, never the credential.

The adapter sends the key as a vendor query parameter. Keep request query strings redacted in external logs.

Apply the account migrations and follow [provider onboarding](providers.md) against the intended deployment. Publication is explicit and disabled by default:

```bash
uv run openmcp providers validate builtwith
uv run openmcp providers register builtwith
uv run openmcp providers list
uv run openmcp providers enable ENDPOINT_ID
```

Registration does not call the vendor or remove other providers. Configure the worker credential and restart the worker before enabling purchases. `OPENMCP_PRODUCT_MODE` chooses the account mode; test mode does not imply free vendor requests.


## Limits and recovery

Only two fixed HTTPS routes are accepted. Inputs cannot supply a target URL, key, arbitrary query parameters or a batch. Redirects are not followed. Responses are bounded to 1 MB and validated before capture. HTTP/vendor errors or malformed results after sending go through the existing API-key review-hold flow (the sent-state policy does not automatically disable the service); retries never submit an already-sent request again. Confirmed results can recover without another vendor call.

Requests are serialized and spaced at least one second apart within an ApiKeyCaller. This assumes the existing single-worker deployment; multiple workers sharing a key would need shared throttling. Free API limit: one request per second.

## Verification

Automated tests mock BuiltWith and exercise PostgreSQL account reservations, worker capture, idempotency replay and saved-result recovery, plus input/response validation, errors and rate spacing. No automated test spends vendor credits.

Two manual vendor calls returned HTTP 200: a free summary of `builtwith.com` and free adoption statistics for `Shopify`. Their actual responses passed adapter validation. These checks did not exercise deployed production billing or the hosted worker. No paid endpoints were called.

Sources: [Free API](https://api.builtwith.com/free-api), [Trends API](https://api.builtwith.com/trends-api).
