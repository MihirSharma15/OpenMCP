import Image from "next/image";
import Link from "next/link";
import AudienceSwitch from "@/components/audience-switch";
import { AuthControls } from "@/components/account/auth-controls";
import { clerkConfigured } from "@/lib/account-config";

export default function Home() {
  return (
    <div className="landing">
      <a href="#main" className="skip-link">Skip to content</a>
      <nav className="landing-nav container" aria-label="Primary">
        <a href="#top" className="wordmark">OpenMCP</a>
        <div className="nav-links">
          <a href="#how">For agents</a>
          <a href="#services">For APIs</a>
          <a href="#endpoints">Docs</a>
          <AuthControls enabled={clerkConfigured()} />
        </div>
      </nav>

      <main id="main" className="landing-main">
        <section id="top" className="hero container">
          <div className="eyebrow accent">Pay-per-call access for AI agents</div>
          <h1>Unlimited APIs. One Wallet.</h1>
          <p className="hero-description">Fund one wallet. Give your AI agent a spending limit. Let it discover useful services, pay per request, and bring the results back. Every purchase and refund in one place.</p>
          <div className="hero-actions">
            <Link href="/dashboard" className="button">Open your wallet</Link>
            <Link href="/demo" className="text-link">Watch an agent pay for data</Link>
          </div>
        </section>

        <div className="hero-art container">
          <Image src="/images/lavender-temple.jpeg" alt="A classical temple in blue mist, a deer in the grass and a lone figure walking past" width={1676} height={938} preload unoptimized sizes="(max-width: 767px) calc(100vw - 40px), (max-width: 1279px) calc(100vw - 96px), 1200px" />
        </div>

        <section className="why-section container section-space">
          <div className="section-heading why-heading">
            <div className="eyebrow">Why now</div>
            <h2>Agents need more services than anyone will sign up for.</h2>
          </div>
          <div className="why-copy muted">
            <p>As agents take on longer tasks, they reach for a wider range of APIs and MCP servers. Today each one means asking a person to create an account and attach a payment method.</p>
            <p>Meanwhile, many sources of useful data give it away for free. As data becomes more valuable to AI, the people who hold it should be paid for it.</p>
          </div>
        </section>

        <AudienceSwitch />

        <section id="endpoints" className="endpoints-section container section-space">
          <div className="section-heading">
            <div className="eyebrow">The skill</div>
            <h2>Three endpoints.</h2>
          </div>
          <div className="endpoint-grid">
            <div><span className="mono">/discover</span><span className="muted">Send a goal and a budget. Get back endpoints that satisfy it, with prices.</span></div>
            <div><span className="mono">/execute</span><span className="muted">Buy a service within your spending allowance. OpenMCP pays the provider and returns the result.</span></div>
            <div><span className="mono">/balance</span><span className="muted">Check how much of the budget the agent has left.</span></div>
          </div>
        </section>

        <section className="demo-callout container">
          <div className="callout-copy">
            <div className="eyebrow accent">Demo</div>
            <h2>Watch an agent run due diligence with a $15 budget.</h2>
            <p className="muted">Three services, three payments, one report on FreightFlow. Every cent is visible as it moves.</p>
            <Link href="/demo" className="button">Open the demo</Link>
          </div>
          <div className="payment-preview" role="table" aria-label="Example service payments">
            <div className="payment-preview-header" role="row"><span role="columnheader">Payment</span><span role="columnheader">Charged</span><span role="columnheader">Provider</span></div>
            <div className="payment-preview-row fresh" role="row"><span role="cell">Legal liabilities</span><span role="cell">$6.00</span><span role="cell">$5.70</span></div>
            <div className="payment-preview-row" role="row"><span role="cell">Operational health</span><span role="cell">$4.00</span><span role="cell">$3.80</span></div>
          </div>
        </section>
      </main>

      <footer className="landing-footer container"><span>OpenMCP</span></footer>
    </div>
  );
}
