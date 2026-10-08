# API2PDF integration

OpenMCP currently supports **one endpoint**, `api2pdf-markdown-to-pdf`.
It converts self-contained Markdown into a downloadable PDF via
`POST https://v2.api2pdf.com/chrome/pdf/markdown`. It returns a temporary hosted
`file_url`, `filename`, vendor reference and `retention_seconds: 86400`.
The agent can present `file_url` as a download link; no PDF bytes pass through MCP.
The link is accessible to whoever has it. The lifetime is measured from vendor
creation, not from every retrieval/replay of the OpenMCP execution. Download before
expiry; replaying an old execution does not regenerate the PDF or renew the link.

## Supported inputs

- `markdown`: nonblank text, maximum 20,000 characters. Headings, lists, emphasis,
  code and normal Markdown hyperlinks are supported.
- `filename`: optional, default `report.pdf`; maximum 100 characters, letters,
  digits, dots, underscores and hyphens only, ending in `.pdf`.

Raw HTML/less-than characters and Markdown image syntax are rejected, **including
inside code blocks**. This deliberately keeps the first integration self-contained
without remote image downloads or embedded HTML/browser code. No rendering
options, custom storage, custom headers, URL-to-PDF, Office conversion, screenshots,
merging or binary-output options are exposed. API2PDF supports more products; they
are not part of this provider's current OpenMCP catalog.

Example execute payload:

```json
{
  "endpoint_id": "api2pdf-markdown-to-pdf",
  "payload": {
    "markdown": "# Research report\n\nFindings from the purchased sources.",
    "filename": "research-report.pdf"
  },
  "max_price_cents": 3
}
```

## Billing and recovery

Retail price: **$0.03 per successful conversion**. The approved standard cluster
has a documented 90-second execution allowance. The provider charges
$0.00019551/compute second plus $0.001/output MB, and a separate $1/month account
fee beginning 30 days after signup. Trial credit does not change retail pricing.
The monthly fee is overhead, not attributed to each execution.

The worker records the vendor-reported `Cost`, preserving its original decimal
representation on the receipt and rounding **up** to whole microdollars for the
integer ledger. For example, $0.00017251586914062501 becomes 173 microdollars.
Do not reuse Exa's requirement for exact integer microdollar costs.

Successful replies must include success, a response ID, a public HTTPS file URL,
and nonnegative finite cost/output size. Reported costs above $0.03 or output
larger than 5 MB go to review. **These are response review bounds, not vendor-side
spending caps**: the vendor may already have charged when an oversized result or
timeout is detected. Bounded text and excluded images/HTML reduce exposure; they
do not guarantee the vendor invoice amount. The worker's configurable timeout
may be shorter than the vendor's 90-second allowance.

The existing flow reserves credits, journals one send, then stores the receipt
and download link before capturing credits. Missing credentials/invalid input
before send are refundable. Timeouts, error replies, missing cost or ambiguous
results after send are held for review, with no automatic paid retry or claim
that the vendor charged zero. Idempotent execution replay returns the same link;
it does not make another conversion. The vendor is not assumed to implement
OpenMCP's idempotency header.

## Setup

1. Set `API2PDF_API_KEY` in the private worker environment (`.env` for local work).
   Keys stay out of discovery, payloads, receipts and browser code. Authorization
   uses the raw key in the header, not a query parameter.
2. Apply the additive `20261007080000_api2pdf.sql` migration with the operator's
   migration credentials. It widens the adapter check; it does not seed providers.
   Use the existing migration tool for the intended schema, including
   `openmcp_product_live` when deploying there. Never edit already-run migrations.
3. Register the provider with the intended database and account mode configured:

   ```sh
   uv run openmcp api2pdf register
   ```

   Or merge into an explicitly configured approved file catalog:

   ```sh
   uv run openmcp api2pdf catalog --output catalog/api2pdf.json --mode test
   ```

   Other providers are preserved. `test` is OpenMCP account mode, **not an API2PDF
   sandbox**; either mode consumes the provider account's real credit.
4. Deploy the updated worker, API and private worker key together. Local JSON
   generation alone does not register the provider in production PostgreSQL.

## Tests

`uv run pytest tests/test_api2pdf.py -q` uses mocked vendor HTTP. PostgreSQL tests
exercise discovery, execute, reservation, worker, capture, persisted receipt/link,
replay and crash recovery. Missing key refunds; uncertain sent requests hold and
cannot resend. No committed test invokes the live provider. A one-off minimal
live conversion can verify the same flow separately without recurring CI spend.

## Official references

Reviewed October 7, 2026:

- [REST specification](https://v2.api2pdf.com/swagger/v2/swagger.json)
- [Markdown endpoint](https://www.api2pdf.com/Convert-Markdown-to-PDF-API-endpoint-now-available)
- [Pricing](https://www.api2pdf.com/pricing)
- [FAQ: limits, account fee and 24-hour retention](https://www.api2pdf.com/faq)
- [Official Python SDK response fields](https://github.com/Api2Pdf/api2pdf.python)

### Local live verification

On October 7, 2026, one tiny conversion passed the discover → execute → local
PostgreSQL reservation → real worker HTTP call → capture → replay workflow.
API2PDF returned HTTP 200 and a valid 36,627-byte PDF. The vendor
reported $0.0004803726082279; the ledger recorded
481 microdollars after rounding up. Retail spending
was three cents in a disposable, simulated-funded local account. Replay made no
additional vendor request. The temporary database schema was dropped and no
production database or real Stripe funding was used. The private local verification
report is ignored at `.openmcp/api2pdf/verified-workflow.json`.
