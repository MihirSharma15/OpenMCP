# Nansen

Three read-only, one-credit routes are integrated into account-mode discover → execute → worker:

This OpenMCP integration **cannot place trades, submit orders, sign blockchain transactions or transfer funds**. Wallet transactions are historical records returned for analysis, not actions the agent can execute. This restriction is explicit in the provider description and every query description exposed through discovery.

- `nansen-wallet-balances`: a page of balances for one wallet and chain. Spam tokens are hidden; amounts and USD values are included when available.
- `nansen-wallet-transactions`: a page of transactions for one wallet and chain, newest first, including hashes, dates and transfer facts. Requires `date.from` and `date.to` as valid `YYYY-MM-DD` dates, ordered and at most 31 days apart.
- `nansen-token-screener`: a current snapshot of tokens across up to five supported chains, with timeframe, sorting and optional liquidity/market-cap/volume filters. This is not historical backtesting or a proprietary Smart Money feed.

Supported chains in this initial adapter: ethereum, base, arbitrum, optimism, polygon, bnb, avalanche and solana. Wallet queries accept one address, not an entity name or a cross-chain aggregate. EVM addresses must contain 40 hex characters after `0x`; Solana addresses must decode to a 32-byte base58 public key.

All queries accept `page` (1–10,000) and `limit` (1–100, default 20). They fetch exactly one page. `pagination.next_page` tells the agent whether another purchase is needed. Dates, wallet/chain compatibility and numeric-filter ordering are checked before any vendor request is sent. Semantic validation failures release the reservation under the existing pre-send policy.

## Pricing and receipts

Each successful OpenMCP request costs **2 USD credit cents**, the current catalog's minimum supported retail price. At the documented one-credit vendor rate, replacement vendor cost is **$0.001**, leaving a $0.019 service markup. This exceeds a percentage-only markup because retail prices currently have a 2-cent minimum.

Nansen's current guide lists these three endpoints at **1 credit on Free and Pro**; the former free-plan 10x multiplier is not used. Free starts with 100 credits, then tops the included balance back up to 10 daily if below 10. Included grants are not an unlimited recurring addition.

`NANSEN_CREDIT_COST_MICROUSD` defaults to 1000 ($10 / 10,000 purchased credits). We record this replacement-cost estimate even while trial credits cover the request, rather than assuming a zero ongoing vendor cost. It is not a confirmed cash invoice. Adjust the private worker setting for a different purchased-credit rate; it must be an integer from 0 to 20,000 microUSD.

The adapter records the response `X-Request-Id` and `X-Nansen-Credits-Used` header. Missing actual-usage headers fall back to the documented one-credit estimate and are labeled accordingly. Successful usage or quoted cost above one credit is held for review. Vendor account balances and private credentials are not exposed in discovery or receipts. API-key purchases do not create Tempo transfers or explorer receipts; their receipt is a vendor request reference.

## Failures and replay

- A structured HTTP 400/401/402/403/404/422/429 rejection with matching status and explicit `X-Nansen-Credits-Used: 0` returns the reserved user credits.
- Errors without conclusive zero-cost evidence, transport failures, malformed success responses and unexpected usage hold the purchase for review. The shared API-key `sent` policy does **not** automatically disable the service.
- An already-sent execution is never automatically submitted again, including after a worker crash. A confirmed saved result can recover and capture without another vendor call. Repeating an idempotency key replays the existing purchase.

Only the three approved HTTPS routes are accepted. The API key travels in the outgoing `apikey` header only. Agent payloads cannot specify URLs, credentials, premium labels or arbitrary upstream options. Redirects are disabled; decoded responses are limited to 1 MB.

## Attribution and scope

Nansen lists balances as redistributable and transactions/token screening as redistributable with attribution. Results include `Powered by Nansen API` and a link to `https://nansen.ai`; discovery descriptions instruct agents to retain that attribution. Show the attribution near the data when building a customer-facing display.

Wallet-label fields and unknown vendor additions are excluded from normalized output. Label lookups, restricted Smart Money feeds, high-cost tools, actions, and other Nansen endpoints are not exposed. Token screening forces general-market `trader_type: all`.

## Setup

Put `NANSEN_API_KEY` in the private worker environment. The catalog contains only the environment-variable name. No new library dependencies are required.

Apply `20261007070000_nansen.sql` with your privileged deployment migration process, together with any earlier unshipped adapter migrations. Do not edit already-run migrations or use the restricted runtime login for DDL. Then register against your target database with the correct product mode:

```sh
uv run openmcp nansen register
```

Registration upserts Nansen without deleting other providers. Deploy the updated API and continuously running worker, including the worker key. Local catalog files do not automatically register providers in production Supabase.

For file-catalog configurations:

```sh
uv run openmcp nansen catalog --output catalog/nansen.json --mode test
```

Use `--mode live` for a live file catalog. The committed example uses account test mode; both account modes call the real Nansen API, not a vendor sandbox.

## Verification

Automated tests mock every Nansen request; running the suite consumes no vendor credits. They cover catalog privacy and merge, strict routes, input and output validation, credit headers, zero-cost rejections, uncertain outcomes, real PostgreSQL reservations/capture, discovery/execute authentication, idempotent replay, and saved-result recovery.

Local verification on October 7, 2026: the focused Nansen + BuiltWith tests passed (111 tests). The full backend suite finished with 758 passed, 2 optional skips, and 1 failure in the unchanged API Creator Chrome form-navigation test (`test_real_browser_restores_approved_form_and_captures_credential`). That test also failed when rerun alone. No Creator browser code was changed as part of this provider integration.

One-off live verification made **three** requests through the local discover → execute → worker flow using a throwaway PostgreSQL schema and simulated Stripe funding. All returned HTTP 200, completed, and reported one credit used. Remaining credits went 100 → 99 → 98 → 97. Replaying the executions made no additional vendor requests. The local test wallet spent 6 cents total, with no reservation left. There were no real card charges or Tempo payments. Production deployment was not tested.

The ignored local summary is `.openmcp/nansen/verified-workflow.json`; no live test script is retained in the repository or automatic suite.

Sources: [credit costs](https://docs.nansen.ai/getting-started/credits), [cash credit pricing](https://release.nansen.ai/en/help/articles/1287744-plans-and-pricing), [redistribution](https://docs.nansen.ai/guides/redistribution-guide), [balances](https://docs.nansen.ai/api/profiler/address-current-balances), [transactions](https://docs.nansen.ai/api/profiler/address-transactions), [token screener](https://docs.nansen.ai/api/token-god-mode/token-screener).
