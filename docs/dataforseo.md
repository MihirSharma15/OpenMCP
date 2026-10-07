# DataForSEO provider

DataForSEO is integrated into **account mode** as one provider with three queries.
The separate testnet demo still reads `catalog/providers.json`. The checked-in
`catalog/dataforseo.json` selects free sandbox endpoints and marks results as demo data.

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

Save `DATAFORSEO_AUTH` privately in the worker environment, or the ignored root
`.env`: base64 of the API login and API password joined with `:`, without a `Basic `
prefix. This is a credential, not encryption. Keep `.env` owner-readable only.
The catalog stores the variable name `DATAFORSEO_AUTH`, never its value. The API,
browser, and LLM do not need the vendor secret.

From the repository root:

```bash
uv run openmcp dataforseo catalog --mode test --output catalog/dataforseo.json
uv run openmcp dataforseo check
```

The check makes three free sandbox requests. Account verification must be complete;
HTTP 403 with API status `40104` indicates pending email/phone verification. A completed
verification can take time to become effective, as observed during initial setup.

Set `OPENMCP_PRODUCT_CATALOG` to the generated catalog path in the **API and worker**,
apply the migration, and restart both with their normal account configuration:

```bash
uv run python -m openmcp.product.cli migrate
uv run python -m openmcp.product.cli database-check
uv run openmcp serve --mode account
uv run python -m openmcp.product.cli worker
```

Run the worker in a separate process. Clerk, Stripe, database, and account MCP
configuration follow [account setup](account-mvp.md). The migration command requires
a privileged database login; the runtime retains its restricted login.

`catalog --output PATH` merges DataForSEO into an existing provider file and preserves
the other providers. Use the deployment's existing approved catalog when one exists.
On startup, OpenMCP replaces its database catalog with the entire configured file;
pointing at a missing or incomplete file can remove other discoverable providers.

For live deployment, generate a separate catalog:

```bash
uv run openmcp dataforseo catalog --mode live --output .openmcp/dataforseo/live-catalog.json
```

Deliver that catalog to both hosts at their configured path and set the vendor secret
on the worker. Alternatively, sync the full approved provider list into PostgreSQL
using `Store.sync_catalog` during an operator migration, then leave
`OPENMCP_PRODUCT_CATALOG` unset on both hosts to preserve the database catalog.
The repository's Vercel packaging excludes `catalog/` and `.openmcp/`; a local file
path alone will not make the file available in a hosted deployment.

The new migration adds `queries.adapter` and `executions.provider_cost_microusd`.
It preserves the existing v1 schema contract for older deployments, so apply it
before rolling out the new API and worker. New code checks that the added columns
exist. Register/enable live DataForSEO services only after both processes are updated.
Never point test credits at billable endpoints; the adapter enforces mode-specific
hosts. A live deployment must use the existing live account settings and schema.

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
uv run openmcp dataforseo check --live --max-cost-usd 0.10
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

## Official MCP server and documentation sources

The official server was built and exercised over MCP stdio at version **3.1.3**,
revision [`1fc6d197f1141cca8d1a242e15804c5adc41916a`](https://github.com/dataforseo/mcp-server-typescript/tree/1fc6d197f1141cca8d1a242e15804c5adc41916a).
Its current tools are `docs_index`, `docs_list_sections`, `docs_search`, and
`api_request`. It does not expose separate named tools for every API endpoint.
Its default request mode uses `.ai` paths; `noAiMode: true` selects the standard API.
The inspected implementation targets the production API, so OpenMCP's sandbox
checks call the sandbox REST API directly.

To reproduce the upstream setup (skip cloning if already present):

```bash
git clone https://github.com/dataforseo/mcp-server-typescript .openmcp/dataforseo/mcp-server
git -C .openmcp/dataforseo/mcp-server checkout 1fc6d197f1141cca8d1a242e15804c5adc41916a
npm --prefix .openmcp/dataforseo/mcp-server ci --ignore-scripts --no-audit --no-fund
npm --prefix .openmcp/dataforseo/mcp-server run build
uv run openmcp dataforseo mcp-check
uv run openmcp dataforseo mcp
```

`mcp-check` starts the server, lists its tools, fetches the three endpoint documents,
and exits. `mcp` runs the official stdio server for an MCP client. The wrapper reads
the private credential and passes only the needed login/password to that child.
Use this for operator exploration; purchases in OpenMCP use the bounded REST adapter
so that discovery, credits, receipts, and retries remain under OpenMCP's control.

The upstream repository is Apache-2.0 licensed. Its checkout retains its license;
no upstream source was copied into the Python adapter. The catalog descriptions
are concise, newly written descriptions of the following documented APIs:

- [Google Organic Live Advanced](https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/)
- [Google Keyword Overview](https://docs.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live/)
- [Google Related Keywords](https://docs.dataforseo.com/v3/dataforseo_labs/google/related_keywords/live/)
- [Sandbox behavior](https://docs.dataforseo.com/v3/appendix-sandbox/) and [API error codes](https://docs.dataforseo.com/v3/appendix/errors/)
- [SERP pricing](https://dataforseo.com/pricing/serp) and [Labs pricing](https://dataforseo.com/pricing/dataforseo-labs)
