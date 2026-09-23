"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getDemoState, LAST_STEP, money } from "@/lib/demo";

export default function Demo() {
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  const state = getDemoState(step);

  useEffect(() => {
    if (!running || step >= LAST_STEP) return;
    const timer = window.setTimeout(() => {
      setStep(current => Math.min(current + 1, LAST_STEP));
      if (step + 1 >= LAST_STEP) setRunning(false);
    }, 1100);
    return () => window.clearTimeout(timer);
  }, [running, step]);

  function run() {
    if (running) { setRunning(false); return; }
    if (step >= LAST_STEP || step === 0) setStep(1);
    setRunning(true);
  }
  function reset() { setRunning(false); setStep(0); }
  function stepOnce() { setRunning(false); setStep(current => Math.min(current + 1, LAST_STEP)); }
  const runLabel = running ? "Pause" : state.complete ? "Run again" : step > 0 ? "Resume" : "Run demo";

  return (
    <div className="demo-page">
      <a href="#demo-main" className="skip-link">Skip to content</a>
      <header className="demo-header">
        <div className="demo-brand">
          <Link href="/" className="demo-wordmark">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3 18V9a7 7 0 0 1 14 0v9" stroke="#161514" strokeWidth="1.6" /><path d="M8 18v-6a2 2 0 0 1 4 0v6" stroke="#6259A6" strokeWidth="1.6" /></svg>
            <span>OpenMCP</span>
          </Link>
          <span className="header-divider" />
          <span className="demo-subtitle">FreightFlow due diligence</span>
        </div>
        <div className="demo-controls">
          <span className="test-mode" title="Simulated payments and sample data. No live Stripe connection or real charges.">Demo mode</span>
          <button type="button" className="reset-button" onClick={reset}>Reset</button>
          <button type="button" className="step-button" onClick={stepOnce} disabled={state.complete}>Step</button>
          <button type="button" className="button run-button" onClick={run}>{runLabel}</button>
        </div>
      </header>

      <main id="demo-main" className="demo-grid">
        <section aria-label="Task" className="panel task-panel">
          <div className="task-caption"><span>Task</span><span className="mono">agent wallet · wal_agent_4c1e</span></div>
          <p>“I am looking into acquiring a mid-sized logistics company called FreightFlow. Build a comprehensive due diligence report on their operational health, hidden legal liabilities, and competitor market share. Here is a $15.00 OpenMCP budget.”</p>
        </section>

        <section aria-label="Budget" className="panel budget-panel">
          <div className="budget-label">Budget remaining</div>
          <div className="budget-amount"><span>{money(state.remaining)}</span><span className="muted">of $15.00</span></div>
          <div className="budget-track" role="progressbar" aria-label="Budget remaining" aria-valuenow={state.remaining / 100} aria-valuemin={0} aria-valuemax={15}><div style={{ width: `${state.remaining / 15}%` }} /></div>
          <div className="budget-summary"><span>Spent {money(state.spent)}</span><span>{state.ledger.length} {state.ledger.length === 1 ? "purchase" : "purchases"}</span></div>
        </section>

        <section aria-label="Current action" className="panel action-panel">
          <div className="stages">
            {["Discover", "Purchase", "Receive", "Report"].map((label, index) => (
              <div key={label} className={`stage ${index === state.stageIndex ? "is-active" : index < state.stageIndex || state.complete ? "is-done" : ""}`} aria-current={index === state.stageIndex ? "step" : undefined}>
                <div className="stage-bar" /><div className="stage-label"><span className="stage-dot" /><span>{label}</span></div>
              </div>
            ))}
          </div>
          <div className="current-action" aria-live="polite" aria-atomic="true">
            <div className="action-heading"><span>{state.actionTitle}</span><span className={step > 0 ? "accent" : "muted"}>{state.actionTag}</span></div>
            <div className="action-code">{state.actionCode}</div>
          </div>
        </section>

        <section aria-label="Services" className="panel services-panel">
          <div className="panel-heading"><h2>Services</h2><span className="mono">from /discover</span></div>
          <div className="table-scroll" role="region" aria-label="Available services" tabIndex={0}>
            <div role="table" aria-label="Service quotes" className="services-table">
              <div role="row" className="service-columns table-heading"><span role="columnheader">Service</span><span role="columnheader">Provider</span><span role="columnheader">Endpoint</span><span role="columnheader" className="align-right">Price</span><span role="columnheader">Status</span></div>
              {state.discovered && state.rows.map(service => (
                <div role="row" key={service.id} className={`service-columns service-row ${service.active ? "active-row" : ""}`}>
                  <span role="cell">{service.name}</span><span role="cell" className="muted">{service.provider}</span><span role="cell" className="mono endpoint-path">{service.endpoint}</span><span role="cell" className="align-right">{money(service.price)}</span><span role="cell"><span className={`status status-${service.status.toLowerCase()}`}>{service.status}</span></span>
                </div>
              ))}
            </div>
          </div>
          {state.discovered ? <div className="quoted-total"><span>Quoted total</span><span>$13.00</span></div> : <div className="empty-state">Services appear once the agent calls /discover.</div>}
        </section>

        <section aria-label="Balances" className="panel balances-panel">
          <div className="panel-heading"><h2>Balances</h2><span>Stripe Connect</span></div>
          <div className="agent-balance"><span>Agent wallet</span><span>{money(state.remaining)}</span></div>
          <div className="earnings-label">Provider earnings</div>
          {state.rows.map(provider => <div key={provider.id} className={`provider-balance ${provider.fresh ? "fresh-payment" : ""}`}><span>{provider.provider}</span><span>{money(provider.earned)}</span></div>)}
          <div className="platform-fees"><span>OpenMCP fees · 5%</span><span>{money(state.fees)}</span></div>
        </section>

        <section aria-label="Payment record" className="panel ledger-panel">
          <div className="panel-heading"><h2>Payment record</h2><span className="mono">via /execute</span></div>
          <div className="table-scroll ledger-scroll" role="region" aria-label="Payment details" tabIndex={0}>
            <div role="table" aria-label="Payment ledger" className="ledger-table">
              <div role="row" className="ledger-columns table-heading"><span role="columnheader">Request</span><span role="columnheader">Service</span><span role="columnheader" className="align-right">Charged</span><span role="columnheader" className="align-right">Provider</span><span role="columnheader" className="align-right">Fee</span></div>
              {state.ledger.map(row => <div role="row" key={row.id} className={`ledger-columns ledger-row ${row.fresh ? "fresh-payment" : ""}`}><span role="cell" className="mono request-id">{row.req}</span><span role="cell">{row.name}</span><span role="cell" className="align-right">{money(row.price)}</span><span role="cell" className="align-right">{money(row.earned)}</span><span role="cell" className="align-right muted">{money(row.fee)}</span></div>)}
            </div>
            {state.ledger.length === 0 && <div className="empty-state">No payments yet. Each purchase settles here as its data arrives.</div>}
            <div className="ledger-columns ledger-total"><span /><span className="muted">Total</span><span className="align-right">{money(state.spent)}</span><span className="align-right">{money(state.spent - state.fees)}</span><span className="align-right muted">{money(state.fees)}</span></div>
          </div>
        </section>

        <section aria-label="Report" className="panel report-panel">
          <div className="panel-heading"><h2>Report</h2><span>{state.complete ? "Complete" : `${state.ledger.length} of 3 sections`} · sample data</span></div>
          <div className="report-body">
            {state.rows.map(report => (
              <div key={report.id} className="report-section">
                <div className="report-heading"><h3 className={report.delivered ? "" : "pending-title"}>{report.name}</h3><span>{report.delivered ? report.provider : "Pending"}</span></div>
                {report.delivered ? <p>{report.text}</p> : <div className="report-placeholder" aria-label="Awaiting service data"><span /><span /></div>}
              </div>
            ))}
            {state.complete && <div className="recommendation"><span>Recommendation</span><p>Proceed to confirmatory diligence. Size the exposure from the open class action before agreeing a term sheet.</p></div>}
          </div>
        </section>
      </main>
    </div>
  );
}
