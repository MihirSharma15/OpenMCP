# OpenMCP frontend

The Next.js website provides the public landing page and a Clerk-authenticated
account dashboard at `/dashboard`, including funding, transactions and agents.
Balances, payments, purchase results and credentials come from the account API.
Provider publication and API Creator currently use operator commands, documented
in [provider onboarding](../docs/providers.md) and [Creator](../openmcp_creator/README.md).

## Run locally

```bash
npm ci
cp .env.example .env.local
npm run dev
```

Configure Clerk keys and the API origins in `.env.local`, then start the API and
worker using [account operations](../docs/operations.md). Open
`http://localhost:3000`. Use that exact origin for `OPENMCP_APP_ORIGIN`, the
backend's `OPENMCP_PRODUCT_FRONTEND_URL`, and Clerk's authorized parties.
`localhost` and `127.0.0.1` are different browser origins. The API itself can use
`http://127.0.0.1:8000`; `OPENMCP_API_URL` must not contain a `/v1` suffix.
`OPENMCP_PUBLIC_API_URL` is the API origin shown in agent setup instructions.

The allowlisted `/api/openmcp/*` proxy obtains the Clerk session token on the
server. FastAPI independently verifies it. Mutations check the website origin;
account responses disable shared caching. Missing configuration produces an
unavailable state. Top-ups use Stripe Checkout and verified backend payment state;
returning to the website cannot credit a balance.

Agent keys appear once and stay only in component memory until saved by the user.
The private connection prompt uses a local credential file. Agent allowances are
lifetime caps, and replacing a key never resets spending.

## Deployment

Use Root Directory `frontend` and the Next.js preset in `vercel.json`. The
repository-root Vercel configuration belongs to the separate FastAPI deployment.
The frontend has no build dependencies outside its directory. Configure Clerk,
`OPENMCP_API_URL`, `OPENMCP_PUBLIC_API_URL` and the exact HTTPS website origin in
the deployed environment. The backend worker is a separate persistent process.

Old `/demo` and `/providers` URLs redirect to `/dashboard`. Their observer apps and
runner proxy have been removed. The public landing page can still use illustrative
examples without relying on that backend.

## Design and checks

Shared components live in `src/components/ui`, account screens in
`src/components/account`, and the development-only UI examples at `/design-system`.
Tokens, typography, focus and reduced-motion styles are in `src/app/globals.css`.

```bash
npm test
npm run build
npm run typecheck
```

Tests cover account formatting and validation, proxy allowlisting, origin checks,
and Checkout retry/terminal-state behavior. See [the API contract](../docs/api-contract.json)
for response examples. The build can run without live payment credentials;
end-to-end sign-in and funding require configured services.
