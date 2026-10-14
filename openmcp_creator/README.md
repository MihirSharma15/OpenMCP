# API Creator

Creator investigates an approved public URL, proposes a bounded adapter, and runs a
sample against the source. A successful job becomes `ready`. An operator then
publishes it into the prepaid account catalog using the same operation as built-in
providers. Creator hosts authenticated HTTP endpoints; the account worker reserves
credits, calls the endpoint and captures the advertised price.

```text
URL + goal + retail price
  → queued → running → ready
                 ↕         → explicit publication → account discovery/purchase
             needs_input
```

## Local setup

```bash
uv sync --extra creator
uv run playwright install chromium
```

Set the following privately in `.env` (see the root `.env.example`):

- `OPENMCP_CREATOR_ADMIN_TOKEN`: at least 16 characters, for job administration.
- `OPENMCP_CREATOR_API_TOKEN`: a different token of at least 16 characters, shared
  with the account worker for generated service calls.
- `OPENMCP_CREATOR_MODEL` and `OPENMCP_CREATOR_INFERENCE_API_KEY`: your configured
  inference model and credential. `OPENMCP_CREATOR_INFERENCE_BASE_URL` selects an
  OpenAI-compatible chat-completions endpoint. No model is chosen automatically.
- `OPENMCP_CREATOR_BASE_URL`: the origin the account worker can reach, default
  `http://127.0.0.1:9002`. Live account publication requires public HTTPS.

```bash
uv run openmcp creator serve
uv run openmcp creator create https://source.example/docs --price-cents 40 \
  --goal "Look up current weather by city"
uv run openmcp creator status
uv run openmcp creator status JOB_ID
```

The server binds to localhost on port 9002 by default (`--port` overrides it).
For hosted use, put a reverse proxy in front and set the public base URL. Run one
Creator process with persistent storage. It includes the research worker and
service host; neither belongs in an ephemeral serverless request handler.
Research, inference and sample validation can consume third-party quota or credit.

## Review and publication

Review the ready job's adapter, source evidence, input and sample before publishing.
Configure the account database and apply its migrations as described in
[operations](../docs/operations.md), then:

```bash
uv run openmcp creator publish JOB_ID
uv run openmcp providers list
uv run openmcp providers enable JOB_ID
```

Publication defaults to disabled. `publish JOB_ID --enable` combines publication
and activation when the service is ready for purchases. The worker environment
must contain `OPENMCP_CREATOR_API_TOKEN` matching the host. Neither discovery nor
catalog exports disclose its value. Creator does not need crypto wallets or a
provider-payment SDK. Source cost remains unknown when no measured cost is
available; receipts do not invent a wholesale/retail split.

## Credentials and account setup

Signup, form submission and other browser interactions pause for approval of the
exact proposed action. Check `status JOB_ID`, complete any manual account steps,
and resume explicitly:

```bash
uv run openmcp creator secret JOB_ID api-key --origin https://source.example
uv run openmcp creator resume JOB_ID --approve-action --note "Account setup complete"
```

The secret command prompts without echoing the value. Credentials and browser state
are encrypted in the local vault and scoped to approved origins. Never put secrets
in a goal or resume note. Additional origins must be specified with `--allow-origin`
when creating the job. CAPTCHA, email verification, account purchases and changed
or ambiguous browser actions may require manual intervention. A pending action
interrupted after submission is not automatically replayed. Document redirects
pass through the checked transport; redirects that resubmit a form, move an
authenticated request to another origin, or redirect a subresource are blocked.

## Hosting and recovery

The admin bearer token protects `/jobs`, `/jobs/{id}` and `/jobs/{id}/resume`.
The separate service bearer token protects `POST /{job_id}`. Service calls require
an `Idempotency-Key` and schema-valid JSON. `/health` is public.

`OPENMCP_CREATOR_STATE_DIR` defaults to `.openmcp/creator`. Its `jobs.sqlite3`
contains job checkpoints and the service-call journal; its vault holds secrets and
browser state. Back up the entire directory together and keep it private. The
account catalog and monetary ledger stay in PostgreSQL. Existing demo jobs are not
migrated automatically; recreate and validate them in the new job store.

A completed service call replays its saved result for the same key and input. A
conflicting payload is rejected. An interrupted or failed source call stays pending
for operator review; it is never automatically repeated. Account recovery also
retains uncertain reservations for review. There is no automatic subscription
purchase, arbitrary generated-code execution, provider self-service dashboard or
multi-tenant isolation in this operator-controlled host.

```bash
uv run pytest tests/test_creator.py tests/test_creator_account.py -q
```
