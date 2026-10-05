# OpenMCP frontend

Next.js App Router implementation of the supplied OpenMCP HTML design.

## Account MVP

The account website is `/dashboard`, with Overview, Transactions, and Agents.
It uses Clerk for human sessions and the FastAPI account API for every balance,
payment, purchase result, and credential operation. The existing local demo and
provider observer remain separate from this account flow.

1. Run `npm install` to install the current Clerk SDK and update the lockfile.
2. Configure Clerk with `npx -y clerk@latest init` and verify with
   `npx -y clerk@latest doctor`. Do not commit generated keys. A claimable Clerk
   development application must be claimed and configured for production before
   accepting real users.
3. Copy the placeholders from `.env.example` into your local environment and
   provide the Clerk keys. Set `OPENMCP_API_URL` to the account FastAPI origin,
   with no `/v1` suffix. `OPENMCP_PUBLIC_API_URL` is the public API origin shown
   in agent connection instructions.
4. Start the account API and worker according to the repository MVP runbook,
   then run `npm run dev` and open **http://localhost:3000**.

Use the exact same website origin for `OPENMCP_APP_ORIGIN`, backend
`OPENMCP_PRODUCT_FRONTEND_URL`, and Clerk's authorized parties/redirect setup.
`localhost` and `127.0.0.1` are different browser origins; mixing them breaks
session/CSRF checks after Checkout returns. The API itself can still use
`http://127.0.0.1:8000`.

The Next.js dev/start commands bind to `localhost` as well. This avoids a local
Next.js/Clerk same-request rewrite being treated as an external proxy request
when the listening hostname and normalized request hostname differ.

The `/api/openmcp/*` route is an allowlisted same-origin proxy. It obtains the
signed-in user's Clerk session token on the server, forwards it to FastAPI for
independent verification, rejects cross-origin mutations, and disables shared
caching. It never forwards the local demo operator token. Missing Clerk or API
configuration produces an unavailable state, never sample money or identities.

Top-ups redirect to Stripe-hosted Checkout; Link appears when enabled and
available on the Stripe account. Browser redirects cannot credit a wallet.
The return page reads an account-owned `top_up_id` and polls verified payment
status. A `canceled=1` parameter only describes navigation. Deposits and service
refunds display backend-confirmed amounts; uncertain purchases remain pending
or under review.

Agent allowances are lifetime caps of $0.01–$10,000 and expire within 30 days.
Keys are displayed once and retained only in component memory. The private
connection prompt saves a local credential file; setup examples never embed
the key. For configured deployments, verify the $10 deposit / $0.40 purchase
journey, a failed-purchase refund, a canceled Checkout, credential revocation,
and sign-out/account switching before enabling live payments.

`npm test` exercises API errors, safe payment/receipt URLs, exact-cent limits,
Checkout retry/terminal-state handling, proxy route allowlisting, and CSRF
origin checks alongside existing demo/provider tests. Full browser and build
checks require the Clerk package to be installed and the external services to
be configured; no development auth substitute is included.

## Existing local demo

Start the Python gateway, providers, traditional APIs, and token-only demo observer from the repository root:

```sh
uv run python -m scripts.run_demo
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The landing page is at `/`, the live FreightFlow demo is at `/demo`, and the provider dashboard is at `/providers`.

## Design

The original Figtree and Geist Mono fonts are self-hosted in `public/fonts`. The supplied temple image is in `public/images`. Desktop dimensions, copy, colors, and typography follow the reference; tablet and phone layouts adapt without horizontal page overflow.

Live balances, earnings, and payment counts use [Magic UI Number Ticker](https://magicui.design/docs/components/number-ticker), adapted in `src/components/ui/number-ticker.tsx` and `src/components/magicui/number-ticker.tsx` with Motion springs. Changes animate from the current value in either direction, currency values retain two decimals, and reduced-motion preferences display the final value immediately. Screen readers receive the actual target value rather than intermediate animation frames. Receipt amounts remain static.

Only `/demo` is an observer for the agent wallet session. It shows three things: the active service budget and separate on-chain wallet balance, a session-budget amount input, and recent transactions with provider, endpoint, charged price, state, and both Tempo receipt links. Applying an amount starts that session at the selected ceiling; the balance ticks down as purchases settle.

**Apply budget** starts a new session, clears that session's transaction history, and sets an enforced spending ceiling. Purchases still come from Claude Code or another MCP-compatible wallet-owning agent. The browser's same-origin `/api/runner/*` target is an observer with only the gateway connection token; it does not load a wallet, sign payments, or return tokens, signed credentials, private keys, or serialized receipt headers. It is safe to keep the page open while the agent buys.

The provider dashboard at `/providers` has Overview, Payments, Services, and Wallets views. It reads `/api/runner/providers`, which proxies the authenticated gateway `/providers/dashboard`. Ledger updates poll every second; chain balances are requested approximately every five seconds, without overlapping polls. All-time ledger earnings survive demo resets. A verified provider receipt counts as received even when data fulfillment is still pending; an agent payment alone never counts as provider earnings. Current-session earnings, historical earnings, and on-chain balances remain separate.

Provider and date filters scope earnings, charts, and payments. Payment history also supports search, status filtering, pagination, receipt details, and CSV export. Reporting dates use the browser timezone; CSV dates are UTC. Exports honor the current filters and leave unsettled received amounts blank. Wallet RPC failures display unavailable, while connection failures preserve the last received ledger with an explicit stale-data message. No example balances are substituted for a disconnected backend.

This remains a local operator workspace, with visibility into all configured providers. It is not a multi-tenant provider login. Historical reporting currently reads the complete local ledger; larger deployments will need server pagination and provider-scoped authorization.

The landing page keeps the original visual style and uses a horizontal “For agents / For APIs” switch to show audience-specific value propositions. Section links select the corresponding audience; the service-registration CTA scrolls to the API view. The switch supports arrow keys, Home/End, and reduced-motion preferences.

## Checks

```sh
npm run typecheck
npm run build
npm test # Node 22.6+ for native TypeScript tests; vitest for src lib tests
```
