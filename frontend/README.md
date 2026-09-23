# OpenMCP frontend

Next.js App Router implementation of the supplied OpenMCP HTML design.

```sh
npm install
npm run dev
```

Open http://127.0.0.1:3000. The landing page is at `/`, and the interactive FreightFlow demo is at `/demo`.

## Design

The original Figtree and Geist Mono fonts are self-hosted in `public/fonts`. The supplied temple image is in `public/images`. Desktop dimensions, copy, colors, and typography follow the reference; tablet and phone layouts adapt without horizontal page overflow.

The demo is a frontend simulation with sample data. Run, Pause, Step, Reset, and Run again control the 12-step sequence. There is no live Stripe connection and no real payment is made. The example service-registration CTA scrolls to the onboarding explanation, as in the supplied design.

## Checks

```sh
npm run typecheck
npm run build
```
