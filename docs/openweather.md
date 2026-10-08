# OpenWeather integration

OpenMCP's account discovery → execution → worker flow calls the Current & Forecast
API collection. The free tier includes current weather and the five-day forecast,
with 60 requests/minute and 1,000,000 requests/month. These are not One Call APIs:
no One Call subscription, card enrollment or paid upgrade is performed.

## Services

- `openweather-current`: current conditions at latitude/longitude, including
  temperature, humidity, pressure, wind and weather descriptions.
- `openweather-forecast`: up to five days of forecasts at three-hour intervals,
  default 40 timestamps; optional `limit` from 1 to 40.

Coordinates are required, latitude -90 to 90 and longitude -180 to 180. Units
are `metric` (default), `imperial` or `standard`. Coordinates must be finite.
This integration does not silently geocode a city or incur additional lookups.
Geocoding can be added as a separately priced service later.

Both services have a fixed $0.02 retail price per successful OpenMCP purchase,
the existing catalog minimum. Free-tier vendor request cost is $0. Receipts label
this `configured_per_request_estimate`; OpenWeather does not return a dollar cost
or a transaction receipt. Paid collection plans have fixed subscription prices,
so there is no universal per-request paid conversion to invent. If you upgrade,
choose an allocated cost for your expected volume and set the microdollar override.
Do not use One Call's $0.0015 overage rate for these separate endpoints.

Sources reviewed October 7, 2026:

- https://openweathermap.org/full-price
- https://openweathermap.org/api/current
- https://openweathermap.org/api/forecast5

## Configuration and registration

Set private `OPENWEATHER_API_KEY` in ignored local `.env` and separately on the
worker host. `OPENWEATHER_REQUEST_COST_MICROUSD` defaults to `0` for the confirmed
free tier. Override with a nonnegative integer no larger than 1,000,000 if needed.
The integration does not check account quotas or automatically change plans.
Both account modes contact the real vendor; neither is an upstream sandbox.

After configuring the intended database, apply migrations and register:

```bash
uv run python -m openmcp.product.cli migrate
uv run openmcp openweather register
```

If Supabase tracks migrations, apply the additive `20261007030000_openweather.sql`
using your existing migration workflow instead. Earlier files are unchanged.
Registration preserves other providers and makes no upstream requests.

For file-managed catalogs, merge into the full configured catalog:

```bash
uv run openmcp openweather catalog --output catalog/all-providers.json --mode test
```

The checked-in `catalog/openweather.json` contains only this provider. Do not
replace the whole marketplace with it. For database-managed catalogs leave
`OPENMCP_PRODUCT_CATALOG` unset on both the API and worker. Deploy the updated
API and worker, configure secrets, migrate and register separately from local tests.

## Request and recovery boundaries

Agents cannot set upstream URLs, methods, credentials, headers or arbitrary
vendor parameters. The adapter revalidates inputs before marking the request sent.
The worker sends one HTTPS GET to the fixed `/data/2.5/weather` or `/forecast`
route, encoding latitude, longitude, units, count and `appid` with HTTPX parameters.
The private key exists only in the outgoing request; it is never added to stored
payloads or normalized results. Because the vendor requires it in the URL,
operators must not enable request-URL logging or expose raw HTTP exceptions.
Redirects and automatic retries are disabled; responses are bounded to 1 MB.

Explicit success code, weather data and timestamps are validated. Forecast results
must be nonempty and within the requested limit. Normalized data includes units,
timezone information when supplied, and OpenWeather attribution. The vendor has
no per-call payment reference; do not present OpenMCP execution IDs as vendor receipts.

After a sent timeout, HTTP rejection or malformed result, the existing workflow
holds the purchase for review without resubmission. Failed requests are not
captured. A configured zero cash cost does not prove a vendor-confirmed unbilled
failure or authorize automatically repeating requests. Saved successful results
recover after crashes and replay without another upstream request.

## Verification

```bash
uv run pytest tests/test_openweather.py -q
```

Automated calls are mocked and consume no vendor quota. PostgreSQL tests verify
discovery, authentication, reservations, credit capture, secret exclusion, replay,
saved-result recovery and migration replay. The live operator check is separately
bounded to one current-weather request and one forecast request.

October 7, 2026 verification: the full Python suite passed with 565 tests and
2 skips, including real isolated PostgreSQL accounting tests with mocked vendors.
The initial live current-weather check returned HTTP 401 before key activation;
it entered review without capture, and no forecast request was submitted.

After activation, a bounded live workflow check successfully exercised both
endpoints through the local API, discovery, authenticated execution, PostgreSQL
reservation, worker vendor request, saved result and credit capture. Both vendor
responses returned HTTP 200; the forecast returned 40 timestamps. Exactly two
vendor requests were made. Replaying each purchase caused neither another vendor
request nor another charge. The simulated 100-cent wallet ended at 96 cents,
with 4 cents spent and no remaining reservations. Stripe funding was simulated;
OpenWeather requests were real. This does not verify the hosted production stack.
The temporary schema was removed and the isolated PostgreSQL server stopped.
Sanitized local evidence is saved in the ignored file
`.openmcp/openweather/verified-workflow.json`.
