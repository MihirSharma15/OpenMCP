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

Open http://127.0.0.1:3000. The landing page is at `/`, and the live FreightFlow demo is at `/demo`.

## Design

The original Figtree and Geist Mono fonts are self-hosted in `public/fonts`. The supplied temple image is in `public/images`. Desktop dimensions, copy, colors, and typography follow the reference; tablet and phone layouts adapt without horizontal page overflow.

Only `/demo` connects to the backend. Run, Step, Pause, Reset, and Run again control real MPP purchases made with valueless pathUSD on Tempo Moderato testnet. The browser uses the same-origin `/api/runner/*` rewrite; the local Python runner owns the agent wallet and never returns keys, API tokens, signed payment credentials, or full receipt headers. Provider report evidence is fictional and labeled in the interface.

The landing page remains the supplied static design. Its service-registration CTA still scrolls to the onboarding explanation.

## Checks

```sh
npm run typecheck
npm run build
```
