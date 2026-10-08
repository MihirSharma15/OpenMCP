# Companies House

Four read-only UK public-register services use the account-mode discover →
execute → worker → credit capture flow. The worker calls the REST API directly;
no separate provider server or MCP server is required.

## Services and prices

- `companies-house-search`: `query` (1–200 characters), optional pagination.
- `companies-house-profile`: `company_number`, exactly eight uppercase letters/digits,
  including leading zeros. Use company numbers returned by search.
- `companies-house-officers`: company number and optional pagination.
- `companies-house-filings`: company number and optional pagination; filing metadata,
  description codes and parameters, not PDF downloads or parsed financial statements.

Each successful query costs 2 OpenMCP USD-credit cents. Public-data upstream
requests have zero per-call cash cost; the retail price is OpenMCP's service fee,
not a Companies House access charge. A valid empty search/list page is a successful
query. List endpoints default to 20 items, support 1–100 per page and an offset of
0–100000. One purchase makes exactly one request, with no automatic pagination.
Results include pagination with `next_start_index`; agents can buy more pages.

## Configuration and registration

Create a live application and an API-key client in the Companies House developer
hub. Set this private variable in the worker environment and ignored local `.env`:

```dotenv
COMPANIES_HOUSE_API_KEY=your_private_key
```

No key belongs in catalog JSON, browser variables or agent credentials. Add the
migration `supabase/migrations/20261007040000_companies_house.sql` through the
existing privileged migration deployment process. It extends the adapter check
constraint without editing older migrations. Runtime Supabase credentials do not
have DDL permissions. For isolated local development, the existing migration
command applies the SQL using the configured schema:

```bash
uv run python -m openmcp.product.cli migrate
uv run openmcp companies-house register
```

Registration upserts this provider and its four queries without deleting others.
It targets the configured database, schema and account mode; local registration
does not register the deployed marketplace. For database-managed catalogs leave
`OPENMCP_PRODUCT_CATALOG` unset on both API and worker. Deploy updated API and
worker code and set the worker's key separately. This integration needs no MPP
signer; other enabled MPP services may still need one.

For a file-managed catalog, merge into the full approved catalog instead:

```bash
uv run openmcp companies-house catalog --output catalog/providers.json --mode live
```

The committed `catalog/companies-house.json` is an isolated test-mode definition.
Do not replace a deployed full catalog with this standalone file.

## Safety and recovery

The catalog fixes the HTTPS origin and approved route templates. The adapter
validates payloads before journaling a send and again when constructing the GET.
Only an eight-character company number can fill a path segment. Inputs cannot
set URLs, headers, credentials or HTTP methods. Basic authentication uses the
private API key as username and an empty password; no credential is placed in
URLs, execution payloads, saved results or discovery responses.

Redirects and automatic vendor retries are disabled. Responses are capped at
1 MB. Profiles must match the requested company; list responses must contain valid
items and bounded pagination. Unknown top-level fields and resource links are
excluded. Results retain Companies House attribution. Officer output includes
public names, roles, appointment dates and correspondence addresses where supplied;
date of birth and identity-verification details are omitted.

HTTP errors (including 401, 404 and 429), timeouts and malformed results after
sending follow the existing review-hold policy: no capture, no automatic refund
or resubmission. An operator must resolve these holds. The shared policy is
conservative even though this upstream API is free. Successful saved results can
recover after a worker crash without requesting the vendor again. Idempotent
OpenMCP purchase replays return the same execution and do not make another call;
this is OpenMCP's guarantee, not a claim about vendor idempotency support.

The vendor documents a shared application rate limit of 600 requests per five
minutes. This adapter has no additional distributed vendor-quota limiter; account
spending controls still apply. At higher traffic, add shared throttling before
sending so rate-limit responses do not create review holds.

## Verification

Automated tests mock vendor requests and cover validation, fixed routes, Basic
authentication, malformed/error responses, empty pages, pagination, accounting,
replay, saved-result recovery and migration reapplication in isolated PostgreSQL.

```bash
uv run pytest tests/test_companies_house.py -q
```

October 7, 2026: full Python suite passed with 609 tests and two optional skips
(testnet MPP spending and dump/restore acceptance). Four bounded live requests
successfully exercised discovery, authenticated execution, reservation, worker
HTTP GET, saved results and credit capture for search, profile, officers and
filings. All returned HTTP 200; search selected TESCO PLC and the remaining
requests used its returned company number. Each replay made no additional
vendor request or charge. The simulated 100-cent wallet ended at 92 cents,
8 cents spent and zero reserved. Stripe funding was simulated; Companies House
requests were real. This verifies the isolated local workflow, not deployed
production. The schema was removed, PostgreSQL stopped and throwaway script
removed. Sanitized local evidence is in the ignored file
`.openmcp/companies-house/verified-workflow.json`.

Live verification is a separate bounded check; automated tests never use the
private account key or vendor quota.

Official references:

- [Application and API-key creation](https://developer.company-information.service.gov.uk/how-to-create-an-application/)
- [Authentication](https://developer.company-information.service.gov.uk/authentication)
- [Rate limits](https://developer.company-information.service.gov.uk/developer-guidelines)
- [Public-data testing](https://developer.company-information.service.gov.uk/api-testing)
- [Company search](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/search/search-companies)
- [Company profile](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/company-profile/company-profile)
- [Officers](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/officers/list)
- [Filing history](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/filing-history/list)
