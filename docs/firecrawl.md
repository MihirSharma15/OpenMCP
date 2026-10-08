# Firecrawl integration

OpenMCP calls Firecrawl v2 REST endpoints through discover → execute → worker.
Credentials remain private in the worker. Enabled services:

- `firecrawl-scrape`: one public HTTPS page as Markdown, **$0.02/request**.
- `firecrawl-scrape-html`: one public HTTPS page as cleaned HTML, **$0.02/request**.
- `firecrawl-search`: up to ten results from **one** web or news source,
  **$0.02/request**. Supports country and day/week/month/year recency filters.
  No automatic scraping of search results.
- `firecrawl-map`: up to ten website URLs, **$0.02/request**. Optional search filter;
  discovers links without scraping their content.

These are fixed package prices. Basic scraping costs one vendor credit and
search costs up to two credits per ten results. The current Hobby PAYG replacement
rate is $5/1,000 credits ($0.005/credit): retail prices cover $0.005/$0.01 plus
$0.015/$0.01 respectively. The catalog's minimum price is $0.02. Your free credits
have zero marginal cash cost; the default accounting rate estimates paid replacement
cost. Fewer results do not reduce the published retail price.

Mapping costs **one vendor credit per call**, regardless of returned URLs, as
specified by Firecrawl's billing page and map feature guide. Its accounting uses
a documented per-call estimate unless the vendor reports actual usage.

Sources reviewed 2026-10-07:

- https://docs.firecrawl.dev/api-reference/endpoint/scrape
- https://docs.firecrawl.dev/api-reference/endpoint/search
- https://docs.firecrawl.dev/api-reference/endpoint/map
- https://docs.firecrawl.dev/features/map
- https://docs.firecrawl.dev/billing
- https://www.firecrawl.dev/pricing

## Configure and register

In ignored root `.env` or the worker's deployment secrets:

```dotenv
FIRECRAWL_API_KEY=your_private_key
FIRECRAWL_CREDIT_COST_MICROUSD=5000
```

The default is the published Hobby top-up replacement rate: `5000` microdollars
($0.005) per credit, from $5 for 1,000 extra credits. This is a configured expense
estimate, not a vendor-reported dollar charge or invoice. It values free-credit
consumption at paid replacement cost for margin planning; it does not create a
cash charge. Set `0` explicitly to value free credits at zero, or override with
your actual contracted per-credit rate for another plan. Restart the worker after
changing it. This setting does not track remaining free credits or automatically
detect plan changes. The integration never enables PAYG.

Apply the additive migration with the privileged migration database URL, then
install/restart the updated API and worker. For a database-managed catalog
(`OPENMCP_PRODUCT_CATALOG` unset), register or update Firecrawl without deleting
other providers:

```bash
uv run python -m openmcp.product.cli migrate
uv run openmcp firecrawl register
```

For a file-managed catalog, merge into the **existing complete approved file**:

```bash
uv run openmcp firecrawl catalog --output catalog/your-existing-catalog.json --mode test
```

Use the same file and `OPENMCP_PRODUCT_MODE` on API and worker. Both account modes
call real Firecrawl and consume vendor credits. The checked-in standalone
`catalog/firecrawl.json` is an example; replacing a complete catalog with it
would remove other providers during startup sync.

The local operator migration command replays idempotent SQL in one transaction,
validating only the latest adapter constraint to preserve newer catalog rows.
Supabase applies the original migration files using its own tracking. Existing
migration files were not edited.

## Request and recovery boundaries

Agents receive the input/output schemas and retail price, never the upstream URL
or API key. Scraping accepts only a public HTTPS URL and an optional
`only_main_content` boolean. Fixed formats, empty `parsers`, basic proxy and a
20-second vendor timeout prevent accidental paid extraction features or PDF
page parsing. Obvious PDF URLs are rejected before sending. Dynamic PDF/file
responses are not delivered as a webpage. No cookies, target headers, browser
actions, screenshots, AI extraction, or session state are accepted. Target DNS
resolution and redirects occur at Firecrawl; the worker itself only contacts
approved Firecrawl URLs. Responses are limited to 1 MB.

Search has fixed single-source selection and no `scrapeOptions` or enterprise
add-ons. Crawl, batch scrape, agent/research and browser sessions require durable
asynchronous job handling and are not part of this synchronous adapter.

Success must be explicit. Scraped content must be nonempty with a successful
origin status. A returned 403/404 page can still cost a vendor credit: no free
refund is inferred from the target status, HTTP error, or `success: false` alone.
Timeouts, malformed results, or unclear billing hold the execution for review.
A sent execution is never automatically resubmitted. Saved results and receipts
recover without another vendor request; execution replay does not spend again.

Search receipts require `creditsUsed`. Scrape responses do not consistently
report per-request credit usage; receipts label the documented one-page count
as an **estimate**, separately from configured cash cost. A reported credit count,
when present, is checked and recorded instead. Estimate fields are not proof
of an invoice or grounds for automatic refunds. Map uses a one-credit per-call estimate, independent of the returned link count.

## Verification

```bash
uv run pytest tests/test_firecrawl.py -q
```

All automated tests mock the vendor and consume zero credits. PostgreSQL tests
use isolated schemas to verify discovery, authentication, reserves, capture,
replay, per-call map billing, migration replay, and saved-result recovery.
Live verification is a separate, explicitly bounded operator action; catalog
and registration commands never make billable vendor calls.

On October 7, 2026, one live Markdown scrape of `https://example.com` completed
through discovery, execution, reservation, the worker, and capture in an isolated
local PostgreSQL schema. Stripe funding was simulated. The test wallet spent
2 cents, and Firecrawl's remaining credits decreased from 1,400 to 1,399.
Replaying the execution made no additional vendor request. The temporary schema
and live-check script were removed afterward. HTML, search, and mapping were
verified with mocked responses; no live requests were made for those endpoints.
