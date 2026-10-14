# DataForSEO provider

DataForSEO is integrated into **account mode** as one provider with three queries.
Test-mode definitions use free sandbox endpoints and label sandbox results.

| Endpoint ID | Input | Result | Initial OpenMCP retail price |
| --- | --- | --- | --- |
| `dataforseo-google-search` | `keyword`, optional location/language/device | First Google results page: organic titles, URLs, snippets and positions | 2 cents |
| `dataforseo-keyword-metrics` | `keywords` (1–100), optional location/language | Search volume, CPC, monthly trends, difficulty and intent when available | 5 cents |
| `dataforseo-related-keywords` | `keyword`, optional `limit` (1–100), location/language | Related keyword ideas and available metrics | 5 cents |

Defaults are US (`location_code=2840`), English (`language_code=en`), and desktop
search. Keyword metrics come from a periodically updated database; they are not
live search-volume measurements. Unknown keywords can be absent. Search results
can contain fewer than ten organic links because the first page includes other
SERP features. The descriptions and JSON schemas exposed by discovery explain
these limits. Retail prices are operator defaults, configurable in the catalog.

## How the LLM discovers and calls it

```mermaid
sequenceDiagram
    participant LLM
    participant MCP as OpenMCP account MCP
    participant API as Account API + Supabase
    participant Worker
    participant DFS as DataForSEO REST API
    LLM->>MCP: discover("Google keyword research")
    MCP->>API: POST /v1/discover
    API-->>LLM: Provider, endpoint IDs, descriptions, schemas, prices
    LLM->>MCP: execute(endpoint_id, payload, max_price_cents, idempotency_key)
    MCP->>API: POST /v1/execute
    API->>API: Validate input and reserve credits
    API-->>LLM: execution_id and pending status
    Worker->>API: Read pending execution and journal one send
    Worker->>DFS: Basic-authenticated POST with one task
    DFS-->>Worker: Task status, results, cost
    Worker->>API: Save result and receipt, capture retail credits
    LLM->>MCP: execution_status(execution_id)
    API-->>LLM: Normalized result and receipt
```

Discovery currently matches words against provider/query names and descriptions;
there is no automatic API crawling or embedding search. Catalog onboarding is an
operator action. The LLM chooses a registered endpoint ID and supplies its schema's
payload; it never receives the upstream credential or chooses a vendor URL.

Example account MCP purchase, after inspecting `discover` and the agent's balance:

```json
{
  "endpoint_id": "dataforseo-google-search",
  "payload": {"keyword": "keyword research tools"},
  "max_price_cents": 2,
  "idempotency_key": "research-google-001"
}
```

Reuse the same key and arguments after a lost response. DataForSEO does not promise
deduplication of an `Idempotency-Key` header. OpenMCP journals the send and never
automatically resubmits it. A timeout or ambiguous result holds the reservation
for review. An explicit vendor rejection with zero reported cost refunds it.
Completed data and the receipt are saved atomically, allowing recovery without
another vendor request if the worker exits before capturing credits.

## Configure the provider

Set `DATAFORSEO_AUTH` to base64 of `API login:API password`, without the `Basic`
prefix, in the private worker environment. Complete vendor account verification.
Do not put the credential in a catalog export or agent configuration.

Apply the account migrations and follow [provider onboarding](providers.md):

```bash
uv run openmcp providers validate dataforseo
uv run openmcp providers register dataforseo
uv run openmcp providers check dataforseo
uv run openmcp providers list
uv run openmcp providers enable ENDPOINT_ID
```

Registration defaults to disabled and never calls the vendor. The separate check
uses the free sandbox by default. `OPENMCP_PRODUCT_MODE` selects test or live
registration; live definitions target billable production endpoints. Publishing
preserves other providers. API and worker startup never synchronize a file catalog.
Configure credentials on the worker and restart it when those credentials change.

## Costs and validation

The adapter fixes search depth to 10 and one page, blocks colon operators and percent
escapes, caps keyword batches/results at 100, and disables paid enrichment options.
DataForSEO bills its prepaid platform balance; OpenMCP separately captures the
catalog's fixed retail price from the user's credits.

Exact vendor costs are stored as integer micro-USD. `provider_cost_cents` remains
available for older consumers, rounded up for fractional-cent DataForSEO costs.
The receipt includes the exact cost and vendor task ID. Sandbox cost is always zero
in the ledger; any illustrative vendor cost remains in `reported_cost_usd`.
Discovery does not label the legacy MPP 90/10 split as a DataForSEO wholesale quote.

Optional **billable** validation:

```bash
uv run openmcp providers check dataforseo --live --max-cost-usd 0.10
```

This submits one small sample to each endpoint. At the prices verified during setup,
the total was **$0.02648**: search $0.002, one keyword overview $0.01212, and three related
ideas $0.01236. The command checks estimated remaining budget before each request and
reported spending afterward. This is not a vendor-enforced account spending cap;
verify pricing before rerunning, and do not automatically retry an ambiguous request.

Relevant tests, with the local PostgreSQL container running:

```bash
OPENMCP_PRODUCT_DATABASE_URL=postgresql://openmcp:openmcp@localhost:5433/openmcp \
OPENMCP_DATABASE_PROVIDER=postgres OPENMCP_REQUIRE_POSTGRES=1 \
uv run pytest tests/test_dataforseo.py tests/test_product_api_call.py \
  tests/test_product_postgres.py tests/test_product_database.py -q
```

## Documentation sources

The bounded REST adapter follows these vendor contracts:

- [Google Organic Live Advanced](https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/)
- [Google Keyword Overview](https://docs.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live/)
- [Google Related Keywords](https://docs.dataforseo.com/v3/dataforseo_labs/google/related_keywords/live/)
- [Sandbox behavior](https://docs.dataforseo.com/v3/appendix-sandbox/) and [API error codes](https://docs.dataforseo.com/v3/appendix/errors/)
- [SERP pricing](https://dataforseo.com/pricing/serp) and [Labs pricing](https://dataforseo.com/pricing/dataforseo-labs)
