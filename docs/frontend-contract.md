# Frontend handoff: visualize both MPP exchanges

Base URL: `http://127.0.0.1:8000`. Send `Authorization: Bearer <OPENMCP_API_TOKEN>`. Default permitted browser origins are localhost/127.0.0.1 on port 3000; configure `OPENMCP_CORS_ORIGINS` as a JSON array if needed.

The demo uses **MPP + Tempo testnet**, with no Stripe dependency. Show five wallet addresses and both payment hops for each purchase. All token balances are real testnet RPC reads; show **testnet / valueless test tokens** visibly.

## Data endpoints

| Route | Purpose |
| --- | --- |
| `GET /balance` | Agent public address, session ID, service spending limit, spent/reserved/remaining cents |
| `POST /discover` | Search results, consumer/provider prices, both recipient addresses and payload schema |
| `GET /dashboard?include_chain=false` | Cheap session earnings and transaction updates |
| `GET /dashboard` | Same plus actual balances of all five wallets from Tempo RPC |
| `GET /transactions` | Active session execution states and two-hop receipts |
| `GET /events?after=<cursor>` | Ordered trace events; response contains `events` and `next_cursor` |
| `POST /demo/reset` | New service allowance; keeps on-chain balances and transaction journals |

Poll the cheap dashboard/events every second and the on-chain dashboard approximately every five seconds. Avoid overlapping outstanding polls. Clear session-only UI data when the session ID changes.

## Prices and labels

| Source | Agent pays | Provider gets | OpenMCP gross fee |
| --- | --- | --- | --- |
| Operations | 0.40 | 0.36 | 0.04 |
| Legal | 0.50 | 0.45 | 0.05 |
| Market | 0.30 | 0.27 | 0.03 |

The full run costs **1.20**, leaving **13.80** of the 15.00 service allowance. These prices are one tenth of the earlier draft. Gross platform fees total 0.12; the actual server wallet gain is slightly lower due to network fees.

Distinguish **service budget remaining** from **on-chain wallet balance**. The faucet grants more tokens than the demo budget, and network fees consume a little extra. `reset` replenishes the service allowance only; it never rewinds the chain. Provider wallets may already contain tokens from rehearsals.

## Dashboard fields

`agent` includes `address`, `session_id`, `budget_cents`, `spent_cents`, `reserved_cents`, and `remaining_cents`. `platform` includes its `address` and `session_gross_fee_cents`. Each `providers` entry includes `endpoint_id`, `name`, `address`, and `session_earned_cents`.

When requested, each of those entries has `wallet_balance`:

```json
{
  "source": "tempo_testnet",
  "address": "0x…",
  "token": "pathUSD",
  "token_address": "0x20c0000000000000000000000000000000000000",
  "chain_id": 42431,
  "balance_units": 360000,
  "decimals": 6,
  "balance": "0.360000",
  "explorer_url": "https://explore.moderato.tempo.xyz/address/0x…"
}
```

The balance is illustrative. If RPC fails, `wallet_balance` has `source` and `error`; display unavailable, not zero. Use the supplied decimal string for display or divide base units by 1,000,000. Service price fields remain integer **cents**, so divide those by 100.

## Two receipts per purchase

Transactions include `price_cents`, `provider_amount_cents`, `platform_fee_cents`, and:

```json
{
  "agent_to_openmcp": {
    "method": "tempo",
    "status": "success",
    "reference": "0x<incoming-transaction-hash>",
    "chain_id": 42431,
    "timestamp": "2026-09-23T00:00:00+00:00",
    "explorer_url": "https://explore.moderato.tempo.xyz/tx/0x…",
    "header": "<serialized MPP Payment-Receipt>"
  },
  "openmcp_to_provider": {
    "method": "tempo",
    "status": "success",
    "reference": "0x<outgoing-transaction-hash>",
    "chain_id": 42431,
    "timestamp": "2026-09-23T00:00:01+00:00",
    "explorer_url": "https://explore.moderato.tempo.xyz/tx/0x…",
    "header": "<serialized MPP Payment-Receipt>"
  }
}
```

Show separate clickable transaction references for **Claude → OpenMCP** and **OpenMCP → provider**. An execution may have only the incoming receipt while fulfillment is pending. Do not show a provider payment as successful until its verified receipt appears. Raw signed credentials and private keys are never returned by the API.

## Trace events

`/events` yields entries with `id`, `session_id`, `execution_id`, `type`, `detail`, and `created` (Unix seconds). The successful sequence is:

1. `agent_challenge_created` — OpenMCP issues its MPP 402 challenge.
2. `agent_payment_submitted` — agent credential received; budget reserved during verification.
3. `agent_payment_confirmed` — includes the incoming receipt; budget becomes spent.
4. `provider_challenge_received` — provider requests its MPP payment.
5. `provider_credential_created` — OpenMCP signs using its own wallet.
6. `provider_payment_confirmed` — outgoing receipt independently checked on-chain.
7. `completed` — both payments and provider data are available.

Repeated unpaid probes can create repeated challenge events. A completed replay returns `replayed: true` without another payment. `session_started` indicates a reset.

## Failure handling and ownership

States are `quoted`, `payment_pending`, `provider_pending`, and `completed`. A provider failure after the first payment leaves the incoming amount spent; it is not automatically refunded. Keep the pending state visible. Domain errors use `{"error":{"code":"…","message":"…","retryable":true}}`; payload validation errors use FastAPI's `detail` array.

Claude's **local** MCP tool handles the agent wallet and MPP payment. The frontend should observe rather than send a plain `/execute` expecting to buy: an unpaid call receives HTTP 402. A browser-based payer would need its own MPP wallet integration. Never copy an agent private key into browser code.

`/demo/reset` is an operator action, not an MCP tool. It refuses while a payment or provider fulfillment is pending. The service uses one local operator connection token; this is a rehearsal environment, not multi-user authentication.
