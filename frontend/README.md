# OpenMCP frontend

Next.js App Router implementation of the supplied OpenMCP HTML design.

Start the Python gateway, providers, traditional APIs, and local wallet runner from the repository root:

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

Live balances, earnings, and payment counts use [Magic UI Number Ticker](https://magicui.design/docs/components/number-ticker), adapted in `src/components/ui/number-ticker.tsx` with Motion springs. Changes animate from the current value in either direction, currency values retain two decimals, and reduced-motion preferences display the final value immediately. Screen readers receive the actual target value rather than intermediate animation frames. Receipt amounts remain static.

Both `/demo` and `/providers` connect to the backend. Run, Step, Pause, Reset, and Run again control real MPP purchases made with valueless pathUSD on Tempo Moderato testnet. The browser uses the same-origin `/api/runner/*` rewrite; the local Python runner owns the agent wallet and never returns keys, API tokens, signed payment credentials, or full receipt headers. Provider report evidence is fictional and labeled in the interface.

The provider dashboard has Overview, Payments, Services, and Wallets views. It reads `/api/runner/providers`, which proxies the authenticated gateway `/providers/dashboard`. Ledger updates poll every second; chain balances are requested approximately every five seconds, without overlapping polls. All-time ledger earnings survive demo resets. A verified provider receipt counts as received even when data fulfillment is still pending; an agent payment alone never counts as provider earnings. Current-session earnings, historical earnings, and on-chain balances remain separate.

Provider and date filters scope earnings, charts, and payments. Payment history also supports search, status filtering, pagination, receipt details, and CSV export. Reporting dates use the browser timezone; CSV dates are UTC. Exports honor the current filters and leave unsettled received amounts blank. Wallet RPC failures display unavailable, while connection failures preserve the last received ledger with an explicit stale-data message. No example balances are substituted for a disconnected backend.

This remains a local operator workspace, with visibility into all configured providers. It is not a multi-tenant provider login. Historical reporting currently reads the complete local ledger; larger deployments will need server pagination and provider-scoped authorization.

The landing page remains the supplied static design. Its service-registration CTA still scrolls to the onboarding explanation.

## Checks

```sh
npm run typecheck
npm run build
npm test # Node 22.6+ for native TypeScript tests
```
