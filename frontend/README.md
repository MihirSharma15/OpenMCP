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

Open http://127.0.0.1:3000. The landing page is at `/`, and the live FreightFlow demo is at `/demo`.

## Design

The original Figtree and Geist Mono fonts are self-hosted in `public/fonts`. The supplied temple image is in `public/images`. Desktop dimensions, copy, colors, and typography follow the reference; tablet and phone layouts adapt without horizontal page overflow.

Only `/demo` connects to the backend. It shows three things: the active service budget and separate on-chain wallet balance, a session-budget amount input, and recent transactions with provider, endpoint, charged price, state, and both Tempo receipt links. Applying an amount starts that session at the selected ceiling; the balance ticks down as purchases settle.

**Apply budget** starts a new session, clears that session's transaction history, and sets an enforced spending ceiling. Purchases still come from Claude Code or another MCP-compatible wallet-owning agent. The browser's same-origin `/api/runner/*` target is an observer with only the gateway connection token; it does not load a wallet, sign payments, or return tokens, signed credentials, private keys, or serialized receipt headers. It is safe to keep the page open while the agent buys.

The landing page remains the supplied static design. Its service-registration CTA still scrolls to the onboarding explanation.

## Checks

```sh
npm run typecheck
npm run build
```
