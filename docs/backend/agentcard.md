# AgentCard integration notes

Reviewed 2026-09-29 against AgentCard's official documentation. The implementation
is under [`openmcp/integrations/agentcard/`](../../openmcp/integrations/agentcard/).
No credentials were used, no cards were issued, and no account settings changed.

## What the docs establish

**Organization authentication.** Exchange `client_id` and `client_secret` using
form-encoded `POST https://api.agentcard.sh/api/v2/oauth/token` with
`grant_type=client_credentials`. Cache the returned token until shortly before
expiry. The organization grant has no refresh token. Sandbox and production use
the same host; the credential determines the mode. `GET /api/v2` reports
`organization_id` and `test_mode`. The adapter checks that mode before onboarding.
Sources: [access token](https://docs.agentcard.sh/api-reference/access-tokens/create),
[credential introspection](https://docs.agentcard.sh/api-reference/access-tokens/introspect).

**User connection.** Organization-authenticated `/api/v2/connect/start` takes one
email or phone, optionally an internal user reference. `/connect/verify` exchanges
the code for a user identity and access/refresh token pair. Capture consent in our
product and record it with `/connect/consent`. The endpoint reference returns an
attempt `id`, while the guide uses `connect_id`; the adapter accepts either.
Sources: [user authentication](https://docs.agentcard.sh/issuing/authenticating-a-user),
[start reference](https://docs.agentcard.sh/api-reference/connections/start).

**Refresh is a mutation.** `/api/v2/connect/refresh` rotates the refresh token.
The docs warn that reusing an already exchanged token outside a short retry window
can revoke the user's connection sessions. Refresh requires durable per-connection
coordination and atomic replacement, including a recovery path for lost replies.
The adapter deliberately sends each request once.
Source: [connection refresh](https://docs.agentcard.sh/api-reference/connections/refresh).

**Issued cards.** The documented flow is connect → consent/identity verification →
fund balance → create card. Issuance uses `https://mcp.agentcard.sh/mcp`, authenticated
with the user's connection token. Use a distinct session per user and discover
schemas with `list_tools`. `create_card` must explicitly set `source: issued`;
omitting it can select a different product. The guide describes `amount_cents`
with a $1 minimum, single-use/multi-use cards, and the `ai_labs` merchant preset.
`add_funds` prepares user checkout and `get_balance` reads spendable funds. A
confirming deposit is a wait state, not an invitation to fund twice.
Sources: [issuing quickstart](https://docs.agentcard.sh/issuing/quickstart),
[issuing a card](https://docs.agentcard.sh/issuing/issuing-a-card).

**Hosted identity verification.** `GET /api/v2/kyc?user_id=...` supplies verification
state and, when action is needed, a short-lived hosted link. Start with that flow
so OpenMCP need not collect identity documents. Sandbox does not exercise every
production state; later test the complete state machine explicitly.
Source: [verification status](https://docs.agentcard.sh/api-reference/identity-verification/status).

**Card credentials and lifecycle.** The MCP credential-reveal tool can put PAN/CVC
in text even when its structured result looks like harmless metadata. Keep raw
MCP results out of logs, dashboard payloads and stored job results. The docs also
describe pause/resume, limit updates, closure and transaction events. Those
operations need owner checks and policy accounting before we expose them.
Source: [using issued cards](https://docs.agentcard.sh/issuing/using-the-cards).

**A different REST card product exists.** `POST /api/v2/cards` creates a card backed
by an added member card, with `Idempotency-Key` and possible approval-pending
responses. That endpoint is not a documented substitute for balance-funded
`source: issued` MCP creation. Do not assume its idempotency guarantee applies to
MCP issuance. Multi-use subscriptions should use the supported issued-card path.
Source: [REST card creation](https://docs.agentcard.sh/api-reference/cards/create).

**Company-funded cards.** AgentCard documents company-wallet, transfer, cardholder
and recovery events. Add this as a separate funding adapter after confirming the
enabled company API with our account. The public issuing overview describes USDC
on Base; existing OpenMCP payments use test pathUSD on Tempo. There is no automatic
balance conversion or bridge in this project.
Sources: [company wallet events](https://docs.agentcard.sh/webhooks/company-wallet/overview),
[AgentCard product FAQ](https://www.agentcard.sh/).

**Webhooks.** Verify `AgentCard-Signature: t=...,v1=...` with HMAC-SHA256 over
`timestamp_bytes + b'.' + raw_body`, with the endpoint secret. Check timestamp
freshness and environment, deduplicate event IDs, persist before returning 2xx,
and process asynchronously. Do not sign the string representation of Python
`bytes` or reserialize JSON. The verifier rejects both old and future timestamps
beyond five minutes; it does not accept the legacy body-only signature. Event
delivery is at least once; successful verification alone is not replay deduplication.
Source: [webhook documentation](https://docs.agentcard.sh/webhooks/overview).

## Implemented now

| File | Behavior |
| --- | --- |
| `config.py` | Independent `AGENTCARD_*` settings; default expected mode is test; no demo settings dependency |
| `models.py` | Typed connection/token/status/card-request models, redacted secrets and sanitized integration errors |
| `client.py` | Async REST adapter; cached organization token, mode introspection, connect/verify/refresh/consent/KYC; no implicit retries or redirects |
| `issuing.py` | Small MCP session interface; runtime paginated schema lookup; explicit issued-card input; balance, funding link, card creation calls |
| `webhooks.py` | Raw-byte HMAC, timestamp, shape and mode verification |
| `tests/test_agentcard.py` | Mock REST/MCP tests of mode separation, token rotation behavior, secret redaction, schema drift, ambiguous creation, signed bytes and replay window |

The card adapter accepts an already initialized official MCP `ClientSession` (or
a test double) through the `ToolSession` protocol. A future connection manager
must resolve an owned encrypted token reference, check environment/expiry, create
a user-scoped session, and close it at the end of the operation. Never hand the
provider bearer to the general-purpose agent: that bypasses OpenMCP's policy layer.

Example of the read-only credential diagnostic, once sandbox credentials are in
the environment:

```python
from openmcp.integrations.agentcard import AgentCardClient, AgentCardSettings

async def check_agentcard():
    async with AgentCardClient(AgentCardSettings()) as client:
        identity = await client.check_credentials()
        return identity.model_dump()  # organization ID and test_mode only
```

`IssuedCards.create(IssuedCardRequest(...))` is a low-level integration operation,
not an authorized backend endpoint. The application must first persist a uniquely
keyed intent, verify the grant, reserve the entire limit, bind the owned connection,
and dispatch through the durable worker. The adapter returns raw MCP results only
to that server-side worker; it does not interpret tool success as payment success.
Normalize documented action states and retain only allowlisted metadata there.

## Not implemented yet

- Public card routes, account ownership, card-intent storage, encrypted token
  persistence/rotation, durable spend reservations or a user-session manager.
- Webhook HTTP ingress, event-ID inbox deduplication, lifecycle reconciliation,
  transaction ledger updates, or external webhook registration.
- Phone verification/funding continuation, credential reveal/checkout handoff,
  card pause/close/limit mutations, subscriptions, company funding or withdrawals.
- Remote service registry/quotes, distributed Tempo signers, automatic refunds.

These belong to the [backend milestones](README.md). Keeping them explicit avoids
exposing a money-moving route behind the demo's single shared connection token.

## First credentialed validation

1. Configure sandbox client credentials through secret storage or a local ignored
   `.env`. Run the read-only diagnostic and confirm the expected organization/mode.
2. Use an explicitly designated test user for code/consent onboarding; bind the
   connect attempt to an authenticated OpenMCP principal. Store encrypted tokens.
3. List MCP tools with that user's token and record sanitized schemas. Confirm
   exact create result shapes, idempotency/correlation support, and status lookup
   with AgentCard before enabling retries. Fail closed on unrecognized schemas.
4. Register a sandbox webhook endpoint, save its signing secret, and exercise
   duplicate, delayed and out-of-order deliveries against the durable inbox.
5. Once intent/policy persistence exists, issue one sandbox card with a bounded
   grant and verify pending/closure/settlement behavior. Inject lost responses and
   restart the worker. An unknown creation must stay reserved and require
   reconciliation, never automatically mint another card.

Ordinary test runs remain offline. Live validation must be a separate opt-in path;
the repository's existing `OPENMCP_LIVE_TEST` controls Tempo tests, not AgentCard.
