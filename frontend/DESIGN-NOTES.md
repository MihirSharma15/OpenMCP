# OpenMCP frontend: design audit and MVP page map

Reviewed September 29, 2026. Scope: `frontend/` source, README, and desktop browser review of `/`, `/demo`, and `/providers`. Backend architecture below follows the supplied product context and frontend interfaces; backend source was outside this review's scope.

## What we are building

OpenMCP gives AI agents one connection to discover and purchase API capabilities, with a wallet and spending limits. Providers can turn their APIs into paid services. The intended API Creator adds a third entry point: submit an upstream API URL and manage the process of turning it into a registered, paid adapter.

Current purchase path: Claude skill → local MCP client / agent wallet → OpenMCP gateway / platform wallet → paid provider wrapper / provider wallet → upstream API. The browser demo uses a separate local Python runner that owns the agent wallet. Each purchase has two independent MPP payments, with OpenMCP retaining the difference before network fees. The demo uses valueless Tempo testnet tokens and fictional upstream data.

Suggested positioning for future copy: **Connect your agent once. Discover APIs and pay per use within your budget.** Complement it with a provider message: **Make your API available to agents and earn per request.** Treat these as proposed copy, not an implemented change.

## Existing routes and functionality

| Route / view | What exists | Current boundary |
| --- | --- | --- |
| `/` | Marketing navigation, hero, temple artwork, rationale, agent/provider setup explanations, three-tool explanation, demo callout | Static marketing. Registration and Docs links scroll to sections; they do not start onboarding or open documentation. |
| `/demo` | FreightFlow task, budget, discovery/purchase/receive/report progress, services, balances, payment ledger, report, Run/Step/Pause/Reset controls | One scripted scenario dependent on the local Python runner; not a general agent account. |
| `/providers#overview` | Earnings metrics/chart, payment split, recent payments, service shortcuts | Local operator workspace showing configured providers; not a provider-scoped account. |
| `/providers#payments` | Search, status/provider/date filters, pagination, CSV export, receipt dialog | Existing useful reporting surface to retain and adapt. |
| `/providers#services` | Registered service cards, endpoint, agent price/provider proceeds/platform fee, payment shortcuts | Read-only service inventory; no add/edit/publish flow. |
| `/providers#wallets` | Provider addresses, balances, ledger/session earnings, explorer links, current agent session | Read-only wallet visibility; no wallet onboarding or lifecycle controls. |

The four provider views are hash navigation within one route. The frontend has no account/authentication, installation, catalog, or API Creator routes.

## Existing design choices

### Visual direction

Quiet, spacious, and editorial on the landing page; compact and operational in the demo and dashboard. Warm neutrals and lavender connect all three surfaces. Large typography and a single atmospheric image supply the marketing personality. Financial screens use restrained panels and visible transaction detail.

### Color tokens

Defined in `src/app/globals.css`:

| Token | Value | Role |
| --- | --- | --- |
| `--page` | `#FAFAF8` | Warm off-white page background |
| `--surface` | `#FFFFFF` | Cards, panels, header surfaces |
| `--ink` | `#161514` | Main text and primary buttons |
| `--muted` | `#71706F` | Supporting text and labels |
| `--line` | `#E6E5E2` | Thin borders and dividers |
| `--soft` | `#F6F6F6` | Code blocks and subdued areas |
| `--lavender` | `#B8B5EC` | Available brand token |
| `--violet` | `#6259A6` | Accent text, selected states, progress |
| `--tint` | `#EFEEFB` | Highlighted rows and accent backgrounds |

Provider screens add muted green (`#39745d` on `#eef5f0`) for success/live states. Amber communicates interrupted connections or pending attention; red communicates errors. Several component colors are hard-coded near these tokens. There is no dark theme.

### Typography and numerical formatting

- Self-hosted **Figtree** for interface text; **Geist Mono** for code, endpoint paths, addresses, and identifiers.
- Predominantly regular and medium weights (400/500), with tight tracking on large headings.
- Landing hero: 56px / 64px line-height, -1.4px tracking; 48px / 56px on tablet and 42px / 48px on phone.
- Landing section headings: 32px / 40px; 28px / 36px on phone. Hero body: 17px / 28px.
- Provider page headings: 34px / 44px, regular weight. Dashboard body and labels are typically 10–14px; panel headings 15–17px.
- Financial values use tabular numerals; currency tickers keep two decimal places. Testnet units are explicitly labeled in the functional screens.

### Layout and spacing

- Landing content is centered at a maximum 1200px, with 48px desktop gutters, 32px tablet gutters, and 20px phone gutters.
- Landing navigation is 72px tall. Hero top padding is 104px; major section spacing is 160px, reduced to 104px and 80px at smaller widths.
- Hero artwork is 1200 × 672 in the desktop layout; smaller layouts preserve its aspect ratio. It uses the existing lavender temple photograph/illustration asset.
- Two-column setup cards and a three-column tool explanation collapse to single columns on smaller screens.
- Demo uses a 12-column grid, 24px gaps, a 64px header, and 48px desktop outer padding. Task/services occupy eight columns and budget/balances four; ledger/report use seven/five.
- Provider dashboard has a fixed 224px left sidebar, approximately 73px top bar, sticky money summary, and a main content region capped at 1456px with 40px desktop padding. Metrics and chart/table panels establish the hierarchy.
- Common panel padding is 20–32px. Dense information remains inside table scroll containers.
- Responsive rules are screen-specific: landing 1279/900/600px, demo 1200/900/600px, providers 1200/960/700px, plus wide-screen adjustments. These were inspected in CSS; this review did not perform a complete mobile QA pass.

### Components, imagery, and motion

- White cards with 1px neutral borders and small 4–6px radii. Shadows are mostly reserved for transient overlays such as dialogs and toasts.
- Marketing/demo primary buttons are near-black pills, generally 44px tall or 36px compact. Dashboard secondary actions use bordered rectangles with approximately 5px radii.
- Underlined text links provide a lighter secondary action. Selected sidebar entries use lavender fills and violet text.
- Custom thin-stroke SVG icons, an arch-shaped brand mark in app screens, and initial-letter provider marks. The landing header uses a text wordmark.
- The lavender temple image appears prominently on the landing page and as a small brand card in the provider sidebar.
- Subtle 150–200ms hover transitions; slower progress/highlight transitions. Motion spring number tickers animate balance and earnings changes; receipt values remain static.
- Existing patterns include status badges, empty states, connection banners, copy controls, filters, CSV export, explorer links, native receipt dialogs, and payment notifications.

### Accessibility and data presentation to preserve

- Skip links, visible violet keyboard focus, labeled controls, table headings/captions, and text descriptions accompanying status colors.
- Reduced-motion CSS and a reduced-motion branch in the number ticker; screen readers receive the settled target value rather than each animation frame.
- Connection failures preserve previously received provider data with a stale-data message. Missing balances display unavailable, not an invented example balance.
- Ledger earnings, session budgets, and on-chain balances are different concepts and are presented separately.
- A provider receipt and successful data delivery are separate states. Keep that distinction throughout purchase history and recovery flows.

## Gaps and inconsistencies to address

1. **Audience and promise:** The hero addresses agents and then immediately speaks to providers. “No accounts, no API keys” needs to mean no separate account/key for every upstream service; it conflicts with the planned OpenMCP account and onboarding if read literally.
2. **Dead-end conversion:** “Register your service” only scrolls to an explanation. “Docs” points at the three-tool summary. There is no working install or signup entry point.
3. **Payment copy:** The landing footer says “Payments by Stripe Connect,” while the functional demo identifies MPP on Tempo testnet. The callout says three payments where three purchases produce six payments.
4. **Pricing examples:** Static landing examples show $6.00 → $5.70 and $4.00 → $3.80 (5% retained), unlike the supplied $0.40 → $0.36 example (10%). Future examples should match the actual selected service and clearly identify test tokens; do not assume one global fee rate.
5. **SDK example:** The landing page advertises `from openmcp import Wrapper`, while the supplied product context identifies an `OpenMCPProvider` decorator. Verify the packaged SDK contract before publishing installation code.
6. **Account boundaries:** The provider workspace includes all providers and the current agent budget. A production provider should see authorized service data; agent spending controls belong in the agent workspace.
7. **Reusable UI:** Shared fonts and tokens exist, but most page components live inside large page-specific files. Extract the shell, brand, actions, forms, notices, tables, and empty states as new flows require them. Preserve the established design rather than adding an unrelated component aesthetic.
8. **Readability and states:** Some dashboard labels are only 10–11px with very light colors. Check contrast and small-screen readability when implementing new pages. In the offline overview, the chart still says “Connecting to your earnings”; recovery copy should match the actual connection state.

## Proposed MVP pages

Paths below are proposals, not existing routes. P0 enables first use, P1 completes day-to-day operation, and P2 is conditional scope. Backend capabilities are dependencies, not frontend-only promises.

| Priority | Page / proposed route | Minimum useful experience | Backend dependency |
| --- | --- | --- | --- |
| P0 | Homepage `/` (refine) | Clear agent/provider paths, working install/register CTAs, accurate payment and demo copy | Final product and SDK contracts |
| P0 | Account entry `/signup`, `/login`, `/onboarding` | Sign in, create account, choose agent/provider setup, resume incomplete onboarding; callback/recovery states as needed by auth method | Authentication, user and provider identities |
| P0 | Install `/install` | Supported Claude skill/MCP setup, copyable instructions, connect account, connection check, first discovery/purchase guidance | Distribution, pairing/authentication, agent registration |
| P0 | Agent home `/app` | Setup checklist, connected agents, available funds, spending limits, recent purchases, next action | Account-scoped agent/wallet/activity APIs |
| P0 | Agents `/app/agents`, `/app/agents/[id]` | Create/connect an agent, see connection state, set per-call and total spending limits, pause/revoke delegation | Agent identity and enforceable delegated policies |
| P0 | Agent wallet `/app/wallet` | Wallet setup/status, supported funding flow, balance, spending reservations, funding history; clear test/live environment | Wallet lifecycle and funding integration |
| P0 | API catalog `/catalog`, `/catalog/[id]` | Search/filter services; inspect purpose, price/unit, schemas, example inputs/outputs, provider, availability; show agent usage instructions | Persistent registry and public discovery contract |
| P0 | Provider setup `/providers/onboarding` | Provider profile, receiving wallet setup, SDK integration steps, verification checklist | Provider identity and wallet lifecycle |
| P0 | Register service `/providers/services/new` | Describe endpoint, provide schema, set pricing, configure upstream authentication, test, preview listing, publish | Registry writes, credential storage, validation and test execution |
| P0 | Documentation `/docs` | Install quickstart, tool reference, provider SDK quickstart, payment/budget explanation, troubleshooting | Stable distribution and API specifications |
| P1 | Agent purchases `/app/activity`, `/app/activity/[id]` | Filters, request/result status, agent charge, provider payment, fee, both receipts, useful recovery states | Account-scoped execution history and results |
| P1 | Provider management `/providers/services/[id]` | Edit service, pricing and schema; view health/test results; manage publication state | Registry updates, versioning, health/status APIs |
| P1 | Provider reporting `/providers` and existing views | Adapt current overview/payments/services/wallets to authenticated provider scope; retain filters, exports, receipt detail | Provider-scoped authorization and scalable reporting |
| P1 | Settings `/app/settings`, `/providers/settings` | Profile, connection/access management, provider details, account sessions; shared settings components | Identity/session/configuration endpoints |
| P1 | API Creator `/create`, `/create/[jobId]` | Submit URL and goal; track investigation, subscription/credential setup, adapter generation, tests, deployment, registration; resolve required input; review before publish | Durable creator jobs, secure credentials, subscription/card workflow, deployment and registry APIs |
| P2 | Cards within Creator/settings | If required for upstream subscriptions: issue/manage delegated cards, limits, merchant/subscription status | Card issuing and lifecycle APIs; not part of the existing MPP wallet UI |

API Creator is a distinct intended product surface. Its placement at P1 is a sequencing proposal: the manual provider integration path can establish registration/testing contracts first. If URL-to-API creation is the launch differentiator, promote Creator to P0. Card setup should appear within that flow when required, rather than become an unexplained primary navigation item.

Keep `/demo` as a clearly labeled public demonstration. Promote agent and provider tasks into separate authenticated workspaces. Payment receipts can remain dialogs where convenient; use a detail route when a shareable/deep link is useful. Recovery, loading, empty, validation, permission-denied, and unavailable states belong within each flow rather than requiring separate navigation pages.

## Recommended build sequence

1. Align homepage positioning and destinations, establish shared form/shell components, and agree on backend contracts for identity and onboarding.
2. Complete the agent path: account → install/connect → wallet/funding → limits → catalog → first purchase → receipt.
3. Complete the provider path: account → receiving wallet → integrate/register → test → publish → existing earnings dashboard.
4. Add Creator as a durable workflow using the same registry, testing, wallet, and service-management interfaces.

## Review and runtime status

- Started `npm run dev` from `frontend/`; Next.js reported ready at `http://127.0.0.1:3000`.
- Visually inspected the landing page, provider overview, and demo in Chrome. Inspected the remaining provider views and responsive rules in source.
- The Python runner is offline, so live balances, purchases, and populated reporting could not be verified. All three frontend routes rendered, including the intended connection/empty states.
- This change records the audit only. No application implementation was changed and no test purchases were initiated.

## Source map

- `src/app/globals.css`: shared tokens, fonts, landing styles, focus and reduced-motion rules.
- `src/app/page.tsx`: current marketing copy, navigation, static examples.
- `src/app/layout.tsx`: global metadata and font preload.
- `src/app/demo/demo.tsx`, `demo.css`: purchase demo and responsive panel layout.
- `src/app/providers/providers.tsx`, `providers.css`: dashboard shell, four views, receipt dialog, styles.
- `src/app/providers/use-provider-data.ts`: provider polling and connection behavior.
- `src/components/ui/number-ticker.tsx`, `wallet-ticker.tsx`: animated numbers and unavailable balance presentation.
- `src/lib/openmcp.ts`, `providers.ts`, `demo.ts`: frontend contracts, formatting and reporting logic.
- `next.config.ts`: same-origin `/api/runner/*` proxy to the local runner, default port 8100.
