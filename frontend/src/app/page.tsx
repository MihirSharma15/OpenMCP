import { Button } from "@/components/ui/button";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check, Play } from "lucide-react";
import AudienceSwitch from "@/components/audience-switch";
import { AuthControls } from "@/components/account/auth-controls";
import { clerkConfigured } from "@/lib/account-config";
import { AmbientScene } from "@/components/landing/ambient-scene";
import { TempleArt } from "@/components/landing/temple-art";
import { ProductDemo } from "@/components/landing/product-demo";
import "./landing.css";

export default function Home() {
  return (
    <div className="landing landing-studio" id="top">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <nav className="landing-nav container" aria-label="Primary">
        <a href="#top" className="wordmark">
          <svg
            className="landing-logomark"
            width="22"
            height="23"
            viewBox="0 0 22 23"
            aria-hidden="true"
          >
            <path d="M11 1 1 18h7l3-5 3 5h7L11 1Z" fill="currentColor" />
            <path d="m8 20 3-5 3 5-3 2-3-2Z" fill="var(--violet)" />
          </svg>
          OpenMCP
        </a>
        <div className="nav-links">
          <a href="#how">For agents</a>
          <a href="#services">For APIs</a>
          <a href="#in-action">How it works</a>
          <AuthControls enabled={clerkConfigured()} />
        </div>
      </nav>

      <main id="main" className="landing-main">
        <section className="landing-hero" aria-labelledby="hero-title">
          <AmbientScene>
            <TempleArt />
          </AmbientScene>
          <div className="hero container">
            <div className="hero-eyebrow eyebrow">
              <span className="hero-eyebrow-line" /> THE INTERNET, OPEN TO YOUR
              AGENT
            </div>
            <h1 id="hero-title">
              Unlimited APIs.
              <br />
              <span>One wallet.</span>
            </h1>
            <p className="hero-description">
              Give your agent the freedom to get things done.
              <br className="hero-description-break" /> One wallet to discover
              services, pay per request,
              <br className="hero-description-break" /> and bring the results
              back.
            </p>
            <div className="hero-actions">
              <Button asChild variant="default" className="hero-primary">
                <Link href="/dashboard">
                  Open your wallet <ArrowUpRight />
                </Link>
              </Button>
              <Button asChild variant="ghost" className="hero-watch">
                <a href="#in-action">
                  <Play size={14} /> See how it works
                </a>
              </Button>
            </div>
            <div className="hero-assurances">
              <span>
                <Check /> Your limits, always
              </span>
            </div>
          </div>
        </section>

        <ProductDemo />

        <section className="why-section container section-space">
          <div className="section-heading why-heading">
            <div className="eyebrow">A MORE OPEN INTERNET</div>
            <h2>
              Good work shouldn’t
              <br />
              stop at a sign-up form.
            </h2>
          </div>
          <div className="why-copy muted">
            <p>
              As agents take on longer tasks, they reach for a wider range of
              APIs and MCP servers. Today each one means asking a person to
              create an account and attach a payment method.
            </p>
            <p>
              Meanwhile, many sources of useful data give it away for free. As
              data becomes more valuable to AI, the people who hold it should be
              paid for it.
            </p>
          </div>
        </section>

        <AudienceSwitch />

        <section
          id="endpoints"
          className="endpoints-section container section-space"
        >
          <div className="section-heading">
            <div className="eyebrow">YOUR AGENT’S TOOLKIT</div>
            <h2>Find it. Buy it. Follow the result.</h2>
          </div>
          <div className="endpoint-grid">
            <div>
              <span className="mono">discover</span>
              <span className="muted">
                Find registered services and review their inputs and prices
                before buying.
              </span>
            </div>
            <div>
              <span className="mono">execute</span>
              <span className="muted">
                Buy a service within your spending allowance. OpenMCP pays the
                provider and returns the result.
              </span>
            </div>
            <div>
              <span className="mono">balance</span>
              <span className="muted">
                Check your wallet’s available funds and your agent’s remaining
                allowance.
              </span>
            </div>
            <div>
              <span className="mono">execution_status</span>
              <span className="muted">
                Follow a pending purchase and retrieve its result or confirmed
                refund.
              </span>
            </div>
          </div>
        </section>

        <section className="account-callout container">
          <div className="callout-copy">
            <div className="eyebrow accent">THE NEXT MOVE IS YOURS</div>
            <h2>
              A little funding.
              <br />A lot of possibility.
            </h2>
            <p className="muted">
              Manage your balance, give each agent a spending allowance, and
              follow its purchases from request to result.
            </p>
            <Button asChild variant="default">
              <Link href="/dashboard" className="button">
                Open your workspace <ArrowRight size={16} />
              </Link>
            </Button>
          </div>
          <nav className="workspace-links" aria-label="Your workspace">
            <Link href="/dashboard">
              <strong>Wallet</strong>
              <span>View your balance and add money</span>
            </Link>
            <Link href="/dashboard/agents">
              <strong>Agents</strong>
              <span>Set allowances and manage access</span>
            </Link>
            <Link href="/dashboard/transactions">
              <strong>Transactions</strong>
              <span>Review purchases, results, and refunds</span>
            </Link>
          </nav>
        </section>
      </main>

      <footer className="landing-footer container">
        <span>OpenMCP</span>
        <span>Made for agents. Controlled by you.</span>
        <a href="#top">Back to top ↑</a>
      </footer>
    </div>
  );
}
