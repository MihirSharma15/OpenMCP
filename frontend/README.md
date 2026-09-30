# OpenMCP frontend

Next.js App Router implementation of the supplied OpenMCP HTML design.

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

Open http://127.0.0.1:3000. The landing page is at `/`, the live FreightFlow demo is at `/demo`, and the provider dashboard is at `/providers`.

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
