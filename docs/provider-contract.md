# Provider handoff: MPP on Tempo testnet

**Replace the earlier Stripe/HMAC wrapper contract with this document.** You own the Python provider wrapper, the three routes, and fictional FreightFlow evidence. OpenMCP owns the agent wallet integration and middleware. Every provider request must be purchased through a genuine **MPP `tempo` / `charge`** exchange.

```text
Claude wallet → MPP → OpenMCP wallet → MPP → your provider wallet
```

OpenMCP first receives an MPP payment from Claude. It then calls your route as an independent paying client. Your wrapper issues its own 402 challenge, validates/broadcasts OpenMCP's signed payment credential using the SDK, then returns your existing endpoint's JSON plus an MPP receipt. Your wrapper is the payee; OpenMCP must not simply transfer money and send you a custom paid flag.

## Network, token, prices, and routes

Use **`pympp[tempo,server,sqlite]==0.11.0`**, the version tested by this repo. Keep the network explicit:

| Setting | Value |
| --- | --- |
| Network | Tempo Moderato **testnet** |
| Chain ID | `42431` |
| RPC | `https://rpc.moderato.tempo.xyz` |
| Token | Test `pathUSD`, six decimals |
| Token contract | `0x20c0000000000000000000000000000000000000` |
| Payment method / intent | `tempo` / `charge` |
| Provider credential header | `Authorization: Payment …` |
| Provider base URL | `http://127.0.0.1:9001` |

All former call prices and absolute fees were divided by ten; OpenMCP retains 10% of the caller's price:

| POST route | Recipient wallet name | Claude pays OpenMCP | **Your MPP charge** | Gross OpenMCP fee |
| --- | --- | --- | --- | --- |
| `/operational-health` | `operations` | 0.40 | **0.36** | 0.04 |
| `/legal-liabilities` | `legal` | 0.50 | **0.45** | 0.05 |
| `/competitor-market-share` | `market` | 0.30 | **0.27** | 0.03 |

These are human-unit test-token amounts. Pass `"0.36"`, `"0.45"`, or `"0.27"` into `Mpp.charge`; the SDK converts them to `"360000"`, `"450000"`, and `"270000"` base units in the challenge. **Do not charge 0.40 for the operational provider hop.** Network fees are additional small test-token charges to the sender.

Every route accepts `{"company":"FreightFlow"}`. Paths and consumer prices are configured in `catalog/providers.json`. OpenMCP computes your price from that catalog and its fee configuration; if either changes, update the provider price to match and restart the services.

## Wallet and secret handoff

`uv run openmcp init` creates five distinct wallets. Obtain your provider's **public address** from `.openmcp/wallets/public.json` and use it as `recipient`. The three private key files are available to the demo owner if later needed, but the chosen receiving flow does **not** require you to load a wallet key: OpenMCP signs the transfer; your SDK validates and broadcasts it.

Create and persist a **separate random MPP challenge-signing secret** for each provider, or a shared secret for one multi-route server with correct request binding. It is an HMAC secret for authenticating the challenge; it is not the wallet key. Do not reuse OpenMCP's `OPENMCP_MPP_SECRET`. No Stripe configuration or old `X-OpenMCP-Signature` is required.

## Request binding and idempotency

OpenMCP sends:

```http
POST /operational-health
Content-Type: application/json
Idempotency-Key: exec_<unique ID>
X-OpenMCP-Execution-ID: exec_<same unique ID>

{"company":"FreightFlow"}
```

Bind the charge to the request:

```python
execution_id = request.headers["Idempotency-Key"]
assert execution_id == request.headers["X-OpenMCP-Execution-ID"]
memo = "0x" + hashlib.sha256(execution_id.encode()).hexdigest()
```

Pass that `memo` and the parsed JSON `body` to `Mpp.charge` on **both the unpaid request and the paid retry**. This causes the SDK to enforce the body digest and memo. The OpenMCP client refuses a challenge without these bindings, on another network/token, with a different recipient, or at a different price. It accepts a single unsponsored charge: do not enable split transfers, sessions, or `fee_payer` for this POC.

Persist results by execution ID and a fingerprint of **route + body**. A retry with changed input must return 409. After successful settlement, cache the verified payment receipt and successful API response. An identical paid retry should return the original response and receipt without running another purchase or generating different data. Verify that the replay's credential/payer matches the original paid request before returning cached data. Keep this cache and the SDK replay store across process restarts.

## SDK integration outline

This is the payment boundary to integrate with your own wrapper and persistent response cache, not a complete provider application:

```python
import hashlib
from mpp import Challenge
from mpp.server import Mpp
from mpp.methods.tempo import ChargeIntent, tempo
from mpp.stores import SQLiteStore
from starlette.responses import JSONResponse

# During application startup; keep instances alive and close them on shutdown.
replay_store = await SQLiteStore.create("provider-mpp.sqlite3")
intent = ChargeIntent(
    chain_id=42431,
    rpc_url="https://rpc.moderato.tempo.xyz",
)
payments = Mpp.create(
    method=tempo(
        intents={"charge": intent},
        chain_id=42431,
        rpc_url="https://rpc.moderato.tempo.xyz",
        currency="0x20c0000000000000000000000000000000000000",
        recipient=PROVIDER_PUBLIC_ADDRESS,
    ),
    realm="supplysignal.local",  # stable across restarts
    secret_key=PROVIDER_MPP_SECRET,
    store=replay_store,
)

# Inside your operational-health route, after payload validation and cache lookup:
body = await request.json()
execution_id = request.headers["Idempotency-Key"]
memo = "0x" + hashlib.sha256(execution_id.encode()).hexdigest()
result = await payments.charge(
    request.headers.get("Authorization"),
    "0.36",
    memo=memo,
    body=body,
)
if isinstance(result, Challenge):
    return JSONResponse(
        {"payment_required": True},
        status_code=402,
        headers={
            "WWW-Authenticate": result.to_www_authenticate(payments.realm),
            "Cache-Control": "no-store",
        },
    )

credential, receipt = result
# Persist verified receipt + request fingerprint here before further work.
data = await your_existing_endpoint(body)
# Persist successful data for identical paid retries before responding.
return JSONResponse(data, headers={"Payment-Receipt": receipt.to_payment_receipt()})
```

Call `await intent.aclose()` and `await replay_store.close()` on shutdown. Validate input before charging. Serialize execution of the same idempotency key so simultaneous retries cannot run the underlying endpoint twice. Do not treat `credential.source` or an arbitrary transaction hash as sufficient proof: the SDK must verify the payment. Use a distinct recipient for each route, with the price in the table.

## Response and failure contract

Return a JSON **object**, at most 1 MB, with `Payment-Receipt` on success:

```json
{
  "company": "FreightFlow",
  "title": "Operational health assessment",
  "content": "Your fictional report text goes here.",
  "sources": [{"id": "operations-2026-q3", "title": "Fleet operating summary"}],
  "is_demo_data": true
}
```

OpenMCP passes the object through. Your content and source schema are flexible; label invented evidence. The middleware makes no LLM report itself.

- Before payment: 402 with the SDK challenge. Never return the underlying data for an unpaid request.
- Invalid input: 422 before settlement. Changed input for an existing execution ID: 409.
- Temporary failure: 503. If payment already settled, preserve it and return the saved receipt where possible. Retry should recover the original result, not charge again.
- OpenMCP requires a parseable MPP receipt, checks its transaction hash against the signed credential, and verifies the exact transfer on-chain before accepting paid success.
- There is no automatic cross-hop rollback. If your operation fails after payment, retain enough state to fulfill the same request on retry; the middleware keeps the execution pending. Do not falsely report a refund.

## Acceptance check with your actual service

1. Start your wrapper on port 9001 using the three recipient addresses.
2. Start OpenMCP with `uv run openmcp serve`; fund the two paying wallets with `uv run openmcp fund` if necessary.
3. Run `uv run openmcp demo`. It should complete three sources with six distinct MPP transaction references.
4. Run it again without reset: references and wallet balances should be unchanged, apart from unrelated activity. No new service payments should occur.
5. Confirm provider wallet increases of **0.36**, **0.45**, and **0.27**; the receiving wallets do not pay the transfer gas.
6. Simulate a lost response after settlement and retry the same key. Confirm a cached receipt/result and no second payment.

The repo's `tests/provider_fixture.py` is an executable reference for the **wire contract**. It uses a test-only in-memory response cache and placeholder content; add persistent caching in your wrapper. `tests/test_live_mpp.py` has verified this contract against the actual Tempo testnet SDK and signer. It does not certify a separate provider implementation until the acceptance check above passes.
