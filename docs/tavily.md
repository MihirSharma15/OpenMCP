# Tavily services

OpenMCP calls Tavily's REST API through the existing discover → execute → worker
flow. Available endpoints:

- `tavily-web-search`: basic search, up to 20 results, **$0.02/request** (one credit).
- `tavily-advanced-search`: advanced search, up to 20 results, **$0.03/request** (two credits).
- `tavily-extract`: basic Markdown extraction from 1–5 URLs, **$0.02/batch**.
- `tavily-advanced-extract`: advanced extraction including tables/embedded content
  from 1–5 URLs, **$0.03/batch**.
- `tavily-map`: map up to 50 website URLs, **$0.05/request**.

Search defaults to ten results and supports general/news/finance topics,
day/week/month/year recency, and included/excluded domains. Increasing basic
search results to 20 does not increase its one-credit cost. Advanced search is
separate so an agent sees the higher price before purchase; no automatic upgrades.

Extraction supports an optional query for relevant content chunks. A partially
successful batch returns successes and failures explicitly and charges the full
published batch price. When every URL fails and the vendor reports zero usage,
OpenMCP refunds the reserved credits. Missing URLs, inconsistent results, or
nonzero usage with no usable extraction require review instead.

Map defaults to 20 links, caps at 50, traverses one level, excludes external links,
and sends no paid natural-language instructions. Crawl and asynchronous research
are not exposed by this adapter. Generated search answers/images are disabled;
use extraction for page content. Response size remains capped at 1 MB.

Sources (reviewed 2026-10-07):
https://docs.tavily.com/documentation/api-reference/endpoint/search,
https://docs.tavily.com/documentation/api-reference/endpoint/extract,
https://docs.tavily.com/documentation/api-reference/endpoint/map, and
https://docs.tavily.com/documentation/api-credits.
The free plan includes 1,000 credits/month; PAYG is $0.008/credit.
Basic/advanced extraction charges 1/2 credits per five successful extractions,
and mapping charges one credit per ten mapped pages. Their reported usage can
be zero until the cumulative threshold is reached; zero is accepted for valid
results and is not itself evidence of a failed request.

## Credentials and pricing

In the ignored root `.env`, or private worker deployment environment:

```dotenv
TAVILY_API_KEY=your_private_key
TAVILY_CREDIT_COST_MICROUSD=8000
```

The default is the published PAYG replacement rate: `8000` microdollars
($0.008) per credit. Receipts separately record vendor-reported credits and the
configured cost basis. This is a configured expense estimate, not proof of an
actual card charge or invoice. Free credits still have zero marginal cash cost;
using the default values them at their paid replacement cost for margin planning.
Set `0` explicitly if you want free-credit consumption valued at zero, or override
with your contracted per-credit rate. Restart the worker after changing it.
This does not query remaining quota, detect plan changes, or enable PAYG.

Fixed prices cover the bounded maximum PAYG replacement cost plus a small
absolute markup: $0.008 + $0.012 for basic search/extract, $0.016 + $0.014 for
advanced search/extract, and at most $0.04 + $0.01 for mapping. Basic pricing
uses the current catalog's $0.02 minimum. Charges are flat per request/batch,
not prorated when an agent requests fewer results/URLs or fewer pages are returned.
During free usage the retail price still applies; cost accounting uses the configured
rate, which defaults to the paid replacement estimate.
Vendor usage accounting does not predict when your free allowance runs out.

## Register and run

Apply the account migrations and follow [provider onboarding](providers.md) against the intended deployment. Publication is explicit and disabled by default:

```bash
uv run openmcp providers validate tavily
uv run openmcp providers register tavily
uv run openmcp providers list
uv run openmcp providers enable ENDPOINT_ID
```

Registration does not call the vendor or remove other providers. Configure the worker credential and restart the worker before enabling purchases. `OPENMCP_PRODUCT_MODE` chooses the account mode; test mode does not imply free vendor requests.


## Minimal verification

Mock tests consume no credits:

```bash
uv run pytest tests/test_tavily.py -q
```

One explicitly requested live check consumes one credit, with no retry:

```bash
uv run openmcp providers check tavily --allow-one-credit
```

The check validates the vendor protocol directly; it does not debit an OpenMCP
account. PostgreSQL tests separately validate discovery, reserves, capture, and replay.

An agent discovers web search then executes `tavily-web-search`, for example with
`payload={"query":"recent renewable energy developments","max_results":3}` and
`max_price_cents=2`, using its existing credential and a unique idempotency key.

Requests are journaled before sending. Stored success can recover after a crash
without another vendor call. A timeout, HTTP error, missing usage, or unexpected
credit count goes to review; no paid request is automatically retried and no
zero-cost refund is inferred from an HTTP error alone. Extraction refunds require
explicit all-URL failure and zero usage. Empty successful search
results are valid and billable. Watch quota in Tavily's dashboard; don't enable
PAYG unless desired. This integration never changes your billing plan.
