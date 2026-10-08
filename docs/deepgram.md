# Deepgram

**Status: WIP — paused while other providers are onboarded.**

Two transcription tools are implemented, with mocked regression coverage and
real Deepgram API verification using an audio-download fixture. Production
onboarding and a real user-hosted mono WAV download remain unverified. Discovery
also needs the complete sample-rate/bit-depth requirements and approved-host
guidance. Broader audio formats and conversion are deferred. This status note
does not disable the existing catalog entries.

Two prerecorded transcription products use the existing account-mode discovery,
execution, worker and credit-capture flow. No separate Deepgram MCP server is
needed. The worker calls the fixed REST `/v1/listen` endpoint with verified audio
bytes and its private API key.

## Input and output

- `deepgram-transcribe-english`: Nova-3 with `language=en`.
- `deepgram-transcribe-multilingual`: Nova-3 with `language=multi` for its supported
  multilingual/code-switching languages.

Both accept the same JSON payload:

```json
{
  "audio_url": "https://YOUR_APPROVED_AUDIO_HOST/recording.wav",
  "diarize": true,
  "smart_format": true
}
```

`audio_url` is required. `diarize` defaults to false; `smart_format` defaults to
true. Each recording must be a mono, uncompressed PCM WAV file: 8–48 kHz, 8/16/24/32
bit integer samples, at most 120 seconds and 12 MB. The worker checks actual frames,
channel count, sample rate and duration and rebuilds the WAV before sending it.
Client-supplied duration is neither accepted nor trusted. Stereo audio, MP3/M4A,
float WAV, local paths, streaming audio and arbitrary vendor options are unsupported.
No decoder installation is required for this first version.

For your own recording, convert locally if needed and upload to a controlled
HTTPS object-storage host approved by the operator. For example:

```bash
ffmpeg -i recording.m4a -ac 1 -ar 16000 -c:a pcm_s16le recording.wav
```

This does not truncate an overlong recording; split recordings longer than two
minutes before purchasing. OpenMCP currently has no audio upload endpoint. Agents
need an existing hosted audio link, supplied by a user or client; attaching a file
to a chat does not itself create a usable URL.

Normalized JSON output includes `provider`, `endpoint_id`, `model`, `request_id`,
`duration_seconds`, `transcript`, `confidence` and `words`. Words include `word`,
`start`, `end`, `confidence`, and optional `punctuated_word` and `speaker`.
Timestamps are seconds into the recording; speaker labels are numeric identifiers,
not verified identities. Silence may produce a valid empty transcript. Raw audio
bytes are not persisted in the database; the original URL and transcript are stored
with the existing execution. Avoid unnecessary private identifiers in URLs.

## Pricing and privacy

Each successful purchase costs 2 OpenMCP USD-credit cents, for up to two minutes.
The catalog's current two-cent minimum is used for this bounded product.
Published Pay As You Go prerecorded Nova-3 rates are $0.0043/minute for monolingual
and $0.0052/minute for multilingual. At the two-minute limit these are $0.0086 and
$0.0104. Smart formatting and prerecorded speaker diarization are included;
other paid add-ons are disabled. Trial credits still consume vendor usage, so
provider cost tracking estimates published paid replacement cost rather than zero.

The saved receipt records Deepgram's request ID and duration, and a microdollar
estimate rounded upward using the published rate. Deepgram does not return an
actual dollar charge in this response; the estimate is not an invoice or exact
billing assertion. Recheck pricing when changing models or account plans.

Every request fixes `mip_opt_out=true`, excluding it from Deepgram's model
improvement program. Deepgram's March 5, 2026 changelog states opting out has no
impact on the listed Pay As You Go/Growth rates. Audio is still sent to Deepgram
for transcription, and transcripts remain in OpenMCP execution history.

## Worker configuration

Set private variables in the worker environment and ignored local `.env`:

```dotenv
DEEPGRAM_API_KEY=your_private_key
DEEPGRAM_AUDIO_HOSTS=static.deepgram.com,your-controlled-bucket.example.com
```

Audio hosts are exact hostnames, comma-separated, with no wildcard matching.
The default is `static.deepgram.com` for official public samples. Your own assets
will not work until their host is added. Approve only trusted public asset hosts;
this is an operator configuration, never an agent input. Shared domains with
uncontrolled proxy endpoints should not be approved. URL checks require HTTPS,
port 443 (or its default), no user info or fragment, and a permitted hostname.
This follows the application's existing trusted-host model; it does not implement
DNS pinning/rebinding protection. Keep these hosts under trusted DNS control.

Downloads carry no Deepgram authorization header, reject redirects, are limited
to 12 MB and finish within the smaller of 30 seconds and the provider timeout.
The verified bytes are uploaded to Deepgram, avoiding a second download of a
possibly changed source. Default vendor request timeout remains the shared
worker setting; long-running or uncertain requests follow existing review policy.

## Migration and catalog registration

Deploy `supabase/migrations/20261007050000_deepgram.sql` through your existing
privileged migration process. It extends the adapter constraint without rewriting
older migrations. Restricted runtime credentials cannot run DDL. For isolated
local development using your configured schema:

```bash
uv run python -m openmcp.product.cli migrate
uv run openmcp deepgram register
```

Registration upserts this provider without deleting others, targeting configured
database, schema and mode. Local registration does not populate production.
Database-managed API and worker deployments must leave `OPENMCP_PRODUCT_CATALOG`
unset. Redeploy updated API and worker code and configure the worker's key and
trusted audio hosts separately. This provider does not require an MPP signer.

For a file-managed catalog, merge into the full approved catalog instead:

```bash
uv run openmcp deepgram catalog --output catalog/providers.json --mode live
```

`catalog/deepgram.json` is an isolated test-mode definition, not a replacement
for the full production marketplace. Existing agent instructions can continue to
use discover/execute and the returned schemas; audio-host setup belongs to the
operator, not the agent.

## Billing and recovery boundaries

Before a paid request is journaled, the adapter validates inputs, key, approved
asset host, audio download and actual PCM duration. A failure here returns the
reserved credits without sending Deepgram a request. After sending, HTTP errors,
timeouts or malformed/mismatched transcription results enter the existing review
hold: no capture and no automatic provider resubmission or refund. Successful
results and estimated costs are saved before capture, enabling crash recovery.
An OpenMCP idempotency replay makes neither another asset fetch nor another paid
call. This is OpenMCP's guarantee, not native Deepgram request deduplication.

## Tests

```bash
uv run pytest tests/test_deepgram.py -q
```

Automated vendor and audio requests are mocked, including real isolated PostgreSQL
reservation, capture, replay and saved-result recovery tests. They use no private
vendor key or trial credits. Live checks are separately bounded.

October 7, 2026: full Python suite passed with 648 tests and two optional skips
(testnet MPP spending and PostgreSQL dump/restore). An unrelated browser test
failed once on navigation timing, passed its focused retry and passed the full
suite rerun; no browser code was changed.

Two real Deepgram requests succeeded (HTTP 200), one per transcription product,
using a 17.566313-second official sample converted to mono in memory. Both
returned 28 timestamped words with speaker labels. The audio-download response
was an in-memory test fixture because the official WAV was stereo; this check
does not verify fetching a user-hosted mono recording. The real public sample
was downloaded without authentication. API discovery, authenticated execution,
PostgreSQL reservation, worker submission, result persistence, credit capture
and idempotent replay all ran locally. Replays made no additional paid calls.
The simulated 100-cent wallet ended at 96 cents, four spent, none reserved.
Combined estimated vendor usage was 2782 microdollars ($0.002782), not a verified
invoice amount. A prior stereo-input rejection sent no Deepgram request and
returned the reservation. Stripe funding was simulated throughout; hosted
production is not verified. Temporary schema/server/script were cleaned up.
Sanitized evidence is in the ignored
`.openmcp/deepgram/verified-workflow.json`.

Official sources:

- [Prerecorded transcription](https://developers.deepgram.com/docs/pre-recorded-audio)
- [REST parameters](https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded)
- [Pricing](https://deepgram.com/pricing)
- [Model improvement opt-out](https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program)
- [March 5 pricing update](https://developers.deepgram.com/changelog/2026/3/5)
