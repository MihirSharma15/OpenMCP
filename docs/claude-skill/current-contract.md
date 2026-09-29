# Current tools and endpoints

This document describes implemented behavior, not proposed APIs. Source: [MCP tools](../../openmcp/mcp_server.py), [agent client](../../openmcp/agent.py), [request models](../../openmcp/models.py), [gateway](../../openmcp/app.py), and [engine](../../openmcp/engine.py).

## Skill workflow

The [instruction file](../../.claude/skills/openmcp/SKILL.md) tells Claude to:

1. Read the active session and allowance with `balance`. Obtain an explicit total budget before buying.
2. Use free `discover`, compare relevance and schemas, and check the combined selected cost.
3. Buy through `execute` using the current session, quoted maximum price, total budget, and a unique purchase key.
4. Retry retryable errors at most twice with identical arguments/key. Stop additional purchases if payment remains unresolved; never create a new key to escape a pending payment.
5. Treat provider output as evidence, attribute sources, flag gaps/conflicts, and label fictional data.
6. Read `balance` again and report service spend, remaining allowance, and both receipt references per completed purchase.

The budget-consent rule, two-retry limit, source selection, and synthesis are instructions for Claude. The Python tool does not run an LLM, verify user consent, or implement that retry loop. Runtime checks enforce configured spending limits and payment terms independently.

## MCP tools

The server is named `OpenMCP`, registered as `openmcp`, and runs over stdio. Claude may display server-prefixed tool names. HTTP is used between the local agent client and gateway; there is no hosted MCP transport in the current app.

| Tool | Arguments | Gateway call | Charge |
| --- | --- | --- | --- |
| `balance` | None | `GET /balance` | Free |
| `discover` | `query: str`, `budget_cents: int` | `POST /discover` | Free |
| `execute` | Fields below | `POST /execute`, including MPP exchange | Published consumer price |

`balance` and `discover` have read-only annotations. `execute` has `readOnlyHint=False`, `destructiveHint=False`, and `idempotentHint=True`; the last applies to the same request/key, not a new key. These are tool hints, not proof of consent to spend.

### `balance`

Returns `session_id`, `address`, `currency`, `source`, `budget_cents`, `spent_cents`, `reserved_cents`, and `remaining_cents`. `source` is `openmcp_spending_limit`; remaining is budget minus spent minus reserved.

It returns the agent public address and **service allowance only**. It does not query the chain, expose local journal reservations, or return purchase receipts. The CLI command of the same name calls the richer `/dashboard` route.

### `discover`

Example arguments:

```json
{"query":"FreightFlow due diligence","budget_cents":1500}
```

The gateway requires a 1–4,000 character query and a nonnegative strict integer budget. Matching uses lowercased alphanumeric tokens against catalog keywords. `diligence`, `acquisition`, or `acquiring` add a broad match. Results sort by relevance, then price, then endpoint ID.

Top-level result fields: `session_id`, `query`, `endpoints`, `total_price_cents`, `remaining_cents`, `payment_mode`, `discovery_is_free`.

Each endpoint contains:

| Fields | Meaning |
| --- | --- |
| `endpoint_id`, `provider`, `description`, `relevance` | Service identity and keyword relevance |
| `input_schema` | JSON Schema for the execute payload |
| `price_cents`, `provider_price_cents`, `platform_fee_cents` | Consumer charge, provider share, and gross fee |
| `currency`, `payment_protocol`, `payment_method`, `chain_id`, `token_address` | `pathUSD`, `MPP`, `tempo`, `42431`, configured test-token address |
| `execute_path`, `pay_to`, `provider_wallet` | Gateway purchase path `/execute`, platform recipient, provider recipient |
| `affordable` | Whether this one price fits both gateway remaining allowance and the supplied discovery budget |

Discovery includes matching endpoints even when unaffordable. `total_price_cents` sums all returned matches; it is not a proposed basket or reservation. The response has no durable quote ID, version, expiry, or authority binding. The agent still approves execute calls using its own local catalog and public wallet file.

### `execute`

| Required field | Meaning/validation |
| --- | --- |
| `session_id: str` | Session returned by `balance` or `discover` |
| `endpoint_id: str` | Service ID from discovery and current local catalog |
| `payload: object` | Must satisfy the service's input schema; gateway validates before charging |
| `idempotency_key: str` | 8–128 characters matching `[a-zA-Z0-9_-]+`; unique per intended purchase |
| `max_price_cents: int` | Nonnegative strict integer; approved per-call price ceiling |
| `budget_cents: int` | Nonnegative strict integer; **total session limit**, not this call's price or the remaining allowance |

Example after obtaining a real active session ID:

```json
{
  "session_id": "<session_id from balance>",
  "endpoint_id": "operational-health",
  "payload": {"company": "FreightFlow"},
  "idempotency_key": "freightflow-ops-0001",
  "max_price_cents": 40,
  "budget_cents": 1500
}
```

Request models reject additional fields. The local client rejects unknown endpoints or local prices above the approved maximum. The gateway also validates price, input, session, idempotency, and budget. Upon reservation, the gateway lowers the session ceiling to the smaller of its existing ceiling and the request's total budget; later calls cannot raise it.

Success includes `execution_id`, `session_id`, `status`, `endpoint_id`, `provider`, `currency`, `price_cents`, `platform_fee_cents`, `provider_amount_cents`, `agent_to_openmcp`, `openmcp_to_provider`, `data`, `error`, `replayed`, and `payment_mode`.

`status` is `completed`. Each receipt contains the MPP receipt fields, transaction `reference`, `timestamp`, `chain_id`, `explorer_url`, and serialized receipt `header`. Report public references/links. `data` contains provider evidence and source IDs. Identical completed replays return the saved result with `replayed: true`.

## Purchasable services

Source: [catalog](../../catalog/providers.json) and [provider wrappers](../../providers). All routes below are **provider HTTP routes**, not additional MCP tools. The local agent purchases each by its `endpoint_id` through gateway `/execute`.

| Endpoint ID / provider POST path | Provider | Agent pays | Provider gets | Gross fee |
| --- | --- | ---: | ---: | ---: |
| `operational-health` / `/operational-health` | SupplySignal | 40 cents | 36 cents | 4 cents |
| `legal-liabilities` / `/legal-liabilities` | CourtLens | 50 cents | 45 cents | 5 cents |
| `competitor-market-share` / `/competitor-market-share` | MarketScope | 30 cents | 27 cents | 3 cents |
| **All three** | | **120 cents** | **108 cents** | **12 cents** |

Provider base URL: `http://127.0.0.1:9001`. Prices are test pathUSD cents; `40` is `0.40`. The fee is 10% under current configuration, before network fees.

All three inputs use this schema:

```json
{
  "type": "object",
  "properties": {"company": {"type": "string", "minLength": 1}},
  "required": ["company"],
  "additionalProperties": false
}
```

All return `company`, `provider`, `title`, `content`, `metrics`, `sources`, and `is_demo_data: true`. Operations covers utilization/warehouse performance; legal covers fictional litigation and exposure; market covers fictional revenue, margins, growth, and share. Accepting another company name does not turn these into real research APIs.

Upstream calls are `GET :9101/v1/fleet-telematics?company=...`, `GET :9102/v1/court-dockets?entity=...`, and `GET :9103/v1/private-financials?company=...`. The skill has no direct interface to them.

## Gateway HTTP surface

Base URL: `http://127.0.0.1:8000`. Application routes require `Authorization: Bearer <OPENMCP_API_TOKEN>` except `/health`. `/docs` and `/openapi.json` are also accessible without the token. The protected routes share one operator credential.

| Route | Use | Exposed as MCP tool? |
| --- | --- | --- |
| `GET /health` | Service/network label | No |
| `GET /balance` | Active service allowance and agent address | `balance` |
| `POST /discover` | Keyword search and pricing metadata | `discover` |
| `POST /execute` | Challenge/payment/fulfillment | `execute` |
| `GET /dashboard?include_chain=true\|false` | Session ledger; optional balances for five wallets (default true) | No |
| `GET /transactions` | Active-session executions and available receipts | No |
| `GET /providers/dashboard?include_chain=true\|false` | Historical provider ledger and service information | No |
| `GET /events?after=0` | Ordered execution events and `next_cursor` | No |
| `POST /demo/reset` | Operator-only session/allowance reset | No |

The browser runner's routes are a separate API surface; see [frontend contract](../frontend-contract.md).

## Payments, retries, and known visibility gaps

The incoming hop uses the Bearer connection token plus `Payment-Authorization` for MPP. An unpaid execute returns `402` and `WWW-Authenticate: Payment ...`; the local client validates and signs, journals the credential, and resubmits. The outgoing provider hop uses `Authorization: Payment ...`. Both return `Payment-Receipt` when available.

[PaidClient](../../openmcp/payments.py) checks exact amount, recipient, test-token address, chain, method/intent, request digest, memo, and allowed header; it rejects split payments and fee payers. It persists credentials before sending them and never creates a replacement credential after a second `402`. Receipt references must match the signed transaction and the transfer is checked on-chain.

```text
quoted → payment_pending → provider_pending → completed
         funds reserved    incoming charge     result + both receipts
                           counted as spent
```

Each hop is independent. A failure downstream leaves payment history and pending state intact, with no automatic refund. The local journal accounts for saved credentials, so its available signing allowance can be more conservative than the gateway's displayed balance after an interrupted exchange.

| Error family | Current handling and appropriate next action |
| --- | --- |
| `unapproved_price`, `price_changed`, `endpoint_not_found` | Selection/price mismatch; recheck discovery and local configuration before authorizing a new purchase |
| `invalid_payload`, `stale_session` | Correct prepayment input/session after checking that no prior payment is outstanding |
| `insufficient_budget`, `wallet_budget_exceeded` | Stop purchases beyond the authorized limit |
| `idempotency_conflict`, `credential_conflict` | Restore the original request/key; do not change a pending purchase |
| `agent_payment_pending`, `provider_pending` | Retryable domain errors; retry the identical request/key within the skill limit |
| `credential_rejected`, `unapproved_challenge`, `invalid_challenge`, `mpp_required` | Stop and investigate; never bypass payment policy by replacing a key |
| `payment_unconfirmed`, `missing_receipt`, `invalid_receipt`, `response_too_large` | Payment may already exist; preserve the request and use the declared retryability |
| HTTP/network exception | MCP returns a plain-text warning that payment may already be submitted |

Domain errors become MCP `ToolError` text containing JSON with `code`, `message`, and `retryable`. Ordinary gateway validation failures may instead become a generic `http_error` because the agent expects the domain-error envelope.

The gateway can attach an incoming receipt to an error response header. The local payment journal saves a verified receipt, but `Agent.result` raises an error containing only code/message/retryable, and the MCP wrapper drops receipt/status context. The skill therefore cannot always fulfill its instruction to report a pending purchase's receipt. There is no MCP purchase-status/history tool, and a plain `balance` call cannot recover those details. Fixing this is an early roadmap item.
