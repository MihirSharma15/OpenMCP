# Exa integration

OpenMCP calls Exa REST APIs through discover → execute → worker. The worker reads
`EXA_API_KEY` privately; discovery exposes schemas and retail prices, never the
key or upstream route.

## Services and pricing

- `exa-search`: Auto search, one query, up to ten results, optional category.
  Returns titles, URLs and available publication metadata. Retail: $0.02/request.
  Published base vendor rate: $0.007/request for up to ten results.
- `exa-contents`: text from one public HTTPS page, 100–20,000 characters,
  default 10,000. Retail: $0.02/request. Published text rate: $0.001/page.

These are fixed package prices; fewer search results or shorter text do not
reduce the retail price. Two cents is the existing catalog minimum. Search uses
`type: auto`; deep research, answer generation, content enrichment, summaries,
subpage crawling, and background jobs are excluded. Contents requests explicitly
disable summaries/highlights and set zero subpages.

Exa's `costDollars` is a response **estimate**, not an invoice: its documentation
says actual billing uses usage counters. Receipts record `vendor_reported_estimate`
and the request ID. Estimates are converted exactly to integer microdollars;
missing, malformed, negative, fractional-microdollar, or over-limit estimates
require review. Search's estimate ceiling is $0.007, contents' is $0.001.
The response ceiling detects unexpected costs after a request, rather than
acting as a vendor-enforced spending limit. Exa dashboard limits remain useful.

Sources reviewed October 7, 2026:

- https://exa.ai/pricing
- https://exa.ai/docs/reference/search
- https://exa.ai/docs/reference/get-contents
- https://exa.ai/docs/contents/quickstart

## Configuration and registration

Set `EXA_API_KEY` in ignored root `.env` for local operation and separately in
private worker deployment secrets. Both OpenMCP test/live account modes contact
the real vendor and consume its balance; neither is an Exa sandbox.

Once `OPENMCP_PRODUCT_DATABASE_URL` is configured for the intended database:

```bash
uv run openmcp account migrate
uv run openmcp exa register
```

Registration adds Exa without pruning other providers. Apply the additive
`20261007020000_exa.sql` migration with your normal Supabase migration process
instead if that manages deployments. Earlier migration files are unchanged.

If using a file-backed catalog instead, merge into the **full** configured file:

```bash
uv run openmcp exa catalog --output catalog/all-providers.json --mode test
```

`catalog/exa.json` contains Exa alone: do not replace a populated marketplace
catalog with it. Catalog generation and registration make no vendor requests.
Deploy/restart the updated backend and worker after provisioning secrets and
registering services. Local isolated test catalogs are not production registration.

## Billing and recovery

Inputs are revalidated before the send journal and network call. Only approved
Exa routes are contacted; target page URLs must be public HTTPS, without local
hosts, literal private addresses, or embedded credentials. Exa handles target
DNS resolution and redirects. No user-supplied headers, vendor URLs, or arbitrary
request options are accepted. The shared response limit is 1 MB.

Successful content retrieval requires a successful per-page status and nonempty,
bounded text. Search may legitimately return an empty list. Timeouts, HTTP errors,
malformed results, unsuccessful page retrieval, and uncertain billing hold the
execution for review after it is sent. A zero cost estimate alone does not prove
an unbilled rejection and does not trigger an automatic refund. Sent calls are
never automatically resubmitted. Saved receipts/results recover after crashes
without repeating a vendor call. Idempotency belongs to OpenMCP's durable journal;
it is not a claim that Exa deduplicates paid requests.

## Verification

```bash
uv run pytest tests/test_exa.py -q
```

All automated vendor calls are mocked, consuming zero Exa balance. PostgreSQL
checks cover discovery, reserves, capture, execution replay, saved-result recovery,
migration replay, and failure holds without resubmission.

On October 7, 2026, initial live searches returned HTTP 200 in Exa's dashboard
but failed inside OpenMCP: the shared HTTP caller reconstructed a response from
already decompressed bytes while retaining `Content-Encoding`, causing another
decompression attempt (`incorrect header check`). The caller now removes stale
encoding/length headers; a mocked gzip regression verifies this fix. The owner
reported two earlier dashboard charges of $0.005 each; upstream success and
OpenMCP workflow completion are distinct.

After the fix, exactly two live requests completed through discovery, execution,
reservation, worker result persistence and capture in an isolated PostgreSQL
schema with simulated Stripe funding:

- Auto search, one result: HTTP 200; response estimated $0.007.
- Single-page text retrieval: HTTP 200; response estimated $0.001.

The test wallet spent 4 cents total and had no remaining reservation. Replaying
both executions made no additional vendor calls. These response estimates total
$0.008 and are not proof of actual dashboard billing. The temporary schema and
live-check script were removed. Production database registration remains separate.
