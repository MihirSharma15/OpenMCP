# API Creator: use Modal and third-party providers

**Team direction: use Modal for Creator compute and hosted adapters, and use
third-party providers for inference, managed browsers, and subscription billing.**
OpenMCP owns the workflow, spending policy, service registry, and paid execution
contract. Keep provider integrations replaceable.

| Capability | Direction | Status now |
| --- | --- | --- |
| Worker execution and adapter hosting | [Modal](https://modal.com/docs/guide/webhooks), with isolated jobs and FastAPI/ASGI services | Local worker and FastAPI host implemented; Modal deployment is next |
| Inference | Third-party model API; configure provider URL, key, and model | OpenAI-compatible Chat Completions JSON client implemented. Native Anthropic would need another client |
| Browser sessions | Third-party managed browsers such as [Browserbase](https://docs.browserbase.com/introduction) | Local Playwright/Chromium implemented; managed session provider is next |
| Subscription funding/cards | Third-party card provider; coordinate with [AgentCard work](../docs/backend/agentcard.md) | Account/card primitives exist elsewhere in the repo; Creator has no card issuance or automatic subscription checkout integration |
| API/data sources | Providers' documented APIs or authorized browser access | JSON GET and rendered-text adapters implemented |

Modal, Browserbase, and automatic subscriptions are **not wired up yet**.
This implementation is a local, single-operator vertical slice. Its seams
(`Inference`, `Browser`, `AdapterRuntime`, and `Worker`) are intended for these
hosted integrations. No inference vendor/model is selected silently.

## What runs today

```text
URL + goal + price + receiving wallet
  -> durable Creator job
  -> browser research + configured inference API
  -> documentation / pricing / signup investigation
  -> credential or approved browser action when needed
  -> validated declarative adapter
  -> real upstream sample + unpaid MPP challenge check
  -> hosted FastAPI route + persistent registry entry
  -> OpenMCP discover / execute -> existing two-hop MPP payments
```

The model produces a typed adapter specification, not unrestricted Python.
The runtime compiles it into a typed FastAPI function using `OpenMCPProvider`.
Validation, receipts, retries, and cached paid responses reuse the provider SDK.
Callers use OpenMCP's existing MCP tools without installing each generated service.

Generated services default to the `openmcp` receiving wallet. This retains service
proceeds in the service wallet, including a self-transfer on the provider hop.
Use `--wallet` to select another initialized receiving wallet. Prices are
**valueless Tempo testnet pathUSD**, not subscription funding or real USD.

## Run locally

```bash
uv sync --extra creator
uv run playwright install chromium
uv run openmcp init
```

Set these in your ignored `.env`:

```dotenv
OPENMCP_CREATOR_INFERENCE_BASE_URL=https://api.openai.com/v1
OPENMCP_CREATOR_INFERENCE_API_KEY=your-provider-key
OPENMCP_CREATOR_MODEL=your-provider-model-id
OPENMCP_CREATOR_BASE_URL=http://127.0.0.1:9002
```

The provider must accept Chat Completions, `response_format: json_object`, and
`max_completion_tokens`. Output is validated locally. See the
[inference API contract](https://developers.openai.com/api/docs/guides/structured-outputs).
Inference is billed by that provider: `max_steps` and output-token limits bound
calls but do not enforce a dollar-denominated inference budget.

Run these in separate terminals:

```bash
uv run openmcp serve
uv run openmcp creator serve
```

Submit a source you have permission to expose:

```bash
uv run openmcp creator create https://example.com/docs \
  --goal 'Expose its documented weather lookup as a paid tool' \
  --price-cents 40 --allow-origin https://api.example.com \
  --key weather-service-001
uv run openmcp creator status
uv run openmcp creator status created-JOB_ID
```

Replace the example URL and job ID. The initial URL origin is authorized for
adapter access; additional API/signup origins must be declared explicitly.
Research can read other public HTTPS documentation. Credentials remain scoped
to one job and origin. Private, metadata, and loopback addresses are rejected;
`OPENMCP_CREATOR_ALLOW_LOOPBACK=true` is a local development exception only.

REST equivalents on port 9002: `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, and
`POST /jobs/{id}/resume`, authenticated with `OPENMCP_API_TOKEN`. Job creation
accepts `url`, `goal`, `price_cents`, `wallet`, `allowed_origins`, `max_steps`, and
`idempotency_key`. Reusing identical input/key returns the job; different input
with the same key returns 409. The CLI shares the local database.

## Signup, credentials, and subscriptions

Jobs pause in `needs_input` with a requirement or proposed browser action.
Review `pending_action` through `status`, then approve that exact action:

```bash
uv run openmcp creator resume created-JOB_ID --approve-action
```

Actions support clicking, filling with a named secret, and capturing an API key
from a selected input/element directly into the vault. Approved fills survive
browser restarts. The worker checkpoints before an action; uncertain outcomes
require account inspection and are never automatically submitted again.

To supply credentials and continue:

```bash
uv run openmcp creator secret created-JOB_ID api-key --origin https://api.example.com
uv run openmcp creator resume created-JOB_ID --note 'Subscription setup is complete; use api-key.'
```

The credential prompt is hidden. Credentials/browser storage are encrypted in
`.openmcp/creator/vault/`; model context and generated specs use secret references.
Protect that directory: the local encryption key sits alongside ciphertext, so
this is not a production KMS boundary. Never paste credentials into goals, notes,
source URLs, or action reasons.

Paid subscriptions currently pause for account/billing setup. Tempo testnet funds
cannot pay a conventional card checkout. The billing integration must bind an owned
AgentCard connection, reserve an explicit spending grant, and persist merchant,
plan, amount, currency, renewal period, transaction reference and status. Reconcile
uncertain charges before retries. Add cancellation and renewal policy as durable
operations. Do not give the investigating model unrestricted card-provider keys.

After a sample failure, resume to retry the saved adapter. Use `--regenerate` with
a corrective `--note` to investigate again within the original step limit.
CAPTCHA/MFA/email verification, unsupported API methods, and exhausted steps remain
explicit requirements rather than fabricated success.

## State and integration contract

- `creator.sqlite3`, next to the gateway database, stores jobs, leases,
  observations, and registrations. Local processes must share this database.
- `.openmcp/creator/services/{id}/` contains `adapter.json`, `catalog.json`, and
  private provider receipt/replay state. Paths follow `OPENMCP_DATABASE`.
- States: `queued -> running -> ready` or `needs_input`. Expired research leases
  resume; uncertain browser mutations require inspection. Step counts survive
  restart. Sample validation makes a real upstream read and may consume quota.
- Only validated services enter the registry. The gateway refreshes it during
  discovery/execution. Authenticated `GET /endpoints/{id}` supplies remote terms;
  the agent checks recipient, network, token, execution path, and user spending
  limits before signing. Endpoint IDs and payment terms remain immutable.
- Ownership is still single-operator. These terms do not implement the future
  multi-tenant, expiring quote protocol.
- Run one Creator host. SQLite claims prevent duplicate research jobs, but provider
  locks and wallet nonces are not distributed. Browser/network checks are defense
  in depth; production needs container-level egress enforcement.

## Modal implementation handoff

1. Package Creator and browser dependencies in a Modal image. Run bounded research
   jobs in isolated [Modal Sandboxes](https://modal.com/docs/guide/sandbox-networking)
   with network restrictions outside the browser.
2. Move job/registry/payment state to a transactional shared database. Do not put
   local SQLite on a shared filesystem and scale payment workers. Preserve lease
   fencing, idempotency keys, and receipt persistence.
3. Add a managed-browser factory with the existing read/interact interface.
   Bind provider sessions to job/credential scope and persist resumable session
   references. Keep local Playwright for tests/development.
4. Deploy generated FastAPI apps with Modal ASGI hosting. Register stable hosted
   URLs after sample validation and MPP checks. Add revision, disable, rollback,
   health monitoring, and credential-rotation operations.
5. Connect subscription grants and AgentCard lifecycle to durable Creator actions.
   Account for source subscription costs separately from per-call revenue.
6. Integrate the hosted registry and quote/ownership system from the backend
   roadmap. SDK-authored and Creator-authored services join the same registry.

## Verification and limits

```bash
uv run pytest -q tests/test_creator.py
uv run ruff check openmcp_creator
```

Tests cover restart/lease behavior, approvals, credential scope, address/redirect
checks, inference output, registration, and a generated-service purchase/replay
using the real MPP SDK with simulated settlement. The optional Chrome test executes
JavaScript in a real browser against controlled HTTP fixtures. Tests do not buy
real subscriptions.

Supported today: JSON GET with scalar query inputs and rendered page text.
Arbitrary generated Python, POST APIs, complex extraction, autonomous card checkout,
distributed hosting, and arbitrary-site success are not implemented. A URL starts
an investigation; it cannot guarantee API availability or redistribution rights.
