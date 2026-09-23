"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  getDemoState,
  money,
  shortAddress,
  shortReference,
  walletAmount,
} from "@/lib/demo";
import {
  type DemoError,
  discoverServices,
  fetchRunnerState,
  pauseRun,
  resetDemo,
  RunnerApiError,
  type RunnerJob,
  type RunnerState,
  startRun,
} from "@/lib/openmcp";

function mergeState(
  previous: RunnerState | null,
  next: RunnerState,
  includedChain: boolean,
): RunnerState {
  if (!previous || previous.dashboard.agent.session_id !== next.dashboard.agent.session_id) {
    return next;
  }
  const eventMap = new Map(
    [...previous.events, ...next.events].map(event => [event.id, event]),
  );
  const dashboard = includedChain
    ? next.dashboard
    : {
        ...next.dashboard,
        agent: {
          ...next.dashboard.agent,
          wallet_balance: previous.dashboard.agent.wallet_balance,
        },
        platform: {
          ...next.dashboard.platform,
          wallet_balance: previous.dashboard.platform.wallet_balance,
        },
        providers: next.dashboard.providers.map(provider => ({
          ...provider,
          wallet_balance: previous.dashboard.providers.find(
            previousProvider => previousProvider.endpoint_id === provider.endpoint_id,
          )?.wallet_balance,
        })),
      };
  return {
    ...next,
    dashboard,
    events: [...eventMap.values()].sort((left, right) => left.id - right.id).slice(-100),
  };
}

function errorDetail(error: unknown): DemoError {
  if (error instanceof RunnerApiError) return error.detail;
  return {
    code: "demo_action_failed",
    message: "The local demo action failed. Retry it without changing the session.",
    retryable: true,
  };
}

export default function Demo() {
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [pollError, setPollError] = useState<DemoError | null>(null);
  const [actionError, setActionError] = useState<DemoError | null>(null);
  const [busy, setBusy] = useState<"run" | "step" | "pause" | "reset" | null>(null);
  const cursorRef = useRef(0);
  const sessionRef = useRef<string | null>(null);
  const nextChainPollRef = useRef(0);
  const autoDiscoveryRef = useRef<string | null>(null);
  const state = getDemoState(runnerState);
  const job = runnerState?.job;
  const running = job?.status === "running" || job?.status === "pausing";

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let controller: AbortController | undefined;

    async function poll() {
      const includeChain = Date.now() >= nextChainPollRef.current;
      controller = new AbortController();
      try {
        const next = await fetchRunnerState(
          cursorRef.current,
          includeChain,
          controller.signal,
        );
        if (!active) return;
        const sessionId = next.dashboard.agent.session_id;
        if (sessionRef.current && sessionRef.current !== sessionId) {
          autoDiscoveryRef.current = null;
          nextChainPollRef.current = 0;
        }
        sessionRef.current = sessionId;
        cursorRef.current = next.next_cursor;
        if (includeChain) nextChainPollRef.current = Date.now() + 5000;
        setRunnerState(previous => mergeState(previous, next, includeChain));
        setPollError(null);
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setPollError(errorDetail(error));
      } finally {
        if (active) timer = window.setTimeout(poll, 1000);
      }
    }

    void poll();
    return () => {
      active = false;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    const sessionId = runnerState?.dashboard.agent.session_id;
    if (
      !sessionId ||
      runnerState.discovery ||
      runnerState.dashboard.transactions.length === 0 ||
      autoDiscoveryRef.current === sessionId
    ) {
      return;
    }
    autoDiscoveryRef.current = sessionId;
    void discoverServices()
      .then(discovery => {
        setRunnerState(previous =>
          previous?.dashboard.agent.session_id === discovery.session_id
            ? { ...previous, discovery }
            : previous,
        );
      })
      .catch(error => setActionError(errorDetail(error)));
  }, [runnerState]);

  function updateJob(nextJob: RunnerJob) {
    setRunnerState(previous => (previous ? { ...previous, job: nextJob } : previous));
  }

  function clearSessionView() {
    setRunnerState(null);
    cursorRef.current = 0;
    sessionRef.current = null;
    nextChainPollRef.current = 0;
    autoDiscoveryRef.current = null;
  }

  async function run() {
    setActionError(null);
    if (running) {
      setBusy("pause");
      try {
        updateJob((await pauseRun()).job);
      } catch (error) {
        setActionError(errorDetail(error));
      } finally {
        setBusy(null);
      }
      return;
    }

    setBusy("run");
    try {
      if (state.complete) {
        await resetDemo();
        clearSessionView();
      }
      updateJob((await startRun("all")).job);
    } catch (error) {
      setActionError(errorDetail(error));
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setActionError(null);
    setBusy("reset");
    try {
      await resetDemo();
      clearSessionView();
    } catch (error) {
      setActionError(errorDetail(error));
    } finally {
      setBusy(null);
    }
  }

  async function stepOnce() {
    setActionError(null);
    setBusy("step");
    try {
      if (!runnerState?.discovery && runnerState?.dashboard.transactions.length === 0) {
        const discovery = await discoverServices();
        setRunnerState(previous => (previous ? { ...previous, discovery } : previous));
      } else {
        updateJob((await startRun("next")).job);
      }
    } catch (error) {
      setActionError(errorDetail(error));
    } finally {
      setBusy(null);
    }
  }

  const runLabel =
    job?.status === "pausing"
      ? "Pausing…"
      : running
        ? "Pause"
        : state.complete
          ? "Run again"
          : state.pending
            ? "Resume"
            : "Run";
  const visibleError = actionError ?? pollError;
  const offline =
    visibleError?.code === "runner_offline" ||
    visibleError?.code === "runner_unavailable" ||
    visibleError?.code === "gateway_unavailable";
  const budgetPercent =
    state.budget > 0 ? Math.max(0, Math.min(100, (state.remaining / state.budget) * 100)) : 0;
  const deliveredCount = state.rows.filter(row => row.delivered).length;

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
          <span className="test-mode" title="Real MPP transfers using valueless Tempo Moderato test tokens.">Tempo testnet · valueless tokens</span>
          <button type="button" className="reset-button" onClick={reset} disabled={running || busy !== null}>Reset</button>
          <button type="button" className="step-button" onClick={stepOnce} disabled={!runnerState || state.complete || running || busy !== null}>Step</button>
          <button type="button" className="button run-button" onClick={run} disabled={!runnerState || busy !== null || job?.status === "pausing"}>{runLabel}</button>
        </div>
      </header>

      <main id="demo-main" className="demo-grid">
        {visibleError && (
          <section className={`demo-banner ${offline ? "offline-banner" : "error-banner"}`} role="alert">
            <strong>{offline ? "Local demo stack offline" : "Demo action failed"}</strong>
            <span>{visibleError.message}</span>
            {offline && <code>uv run python -m scripts.run_demo</code>}
          </section>
        )}
        {job?.last_error && (
          <section className="demo-banner error-banner" role="alert">
            <strong>Purchase needs attention</strong>
            <span>{job.last_error.message}</span>
            <span>{job.last_error.retryable ? "Run resumes the same idempotent request." : "Resolve the gateway error before retrying."}</span>
          </section>
        )}
        {state.pending && !job?.last_error && (
          <section className="demo-banner pending-banner" role="status">
            <strong>Purchase pending</strong>
            <span>Run will resume {state.pending.provider} with the same payment credential and idempotency key—no second payment is created.</span>
          </section>
        )}
        <section aria-label="Task" className="panel task-panel">
          <div className="task-caption"><span>Task</span><span className="mono" title={state.agent?.address}>agent wallet · {shortAddress(state.agent?.address)}</span></div>
          <p>“I am looking into acquiring a mid-sized logistics company called FreightFlow. Build a comprehensive due diligence report on their operational health, hidden legal liabilities, and competitor market share. Here is a 15.00 test-pathUSD OpenMCP budget.”</p>
        </section>

        <section aria-label="Budget" className="panel budget-panel">
          <div className="budget-label">Service budget remaining · test pathUSD</div>
          <div className="budget-amount"><span>{state.agent ? money(state.remaining) : "—"}</span><span className="muted">of {state.agent ? money(state.budget) : "—"}</span></div>
          <div className="budget-track" role="progressbar" aria-label="Service budget remaining" aria-valuenow={state.remaining / 100} aria-valuemin={0} aria-valuemax={state.budget / 100 || 15}><div style={{ width: `${budgetPercent}%` }} /></div>
          <div className="budget-summary"><span>Spent {money(state.spent)} · reserved {money(state.reserved)}</span><span>{state.ledger.length} {state.ledger.length === 1 ? "execution" : "executions"}</span></div>
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
            <div className="action-heading"><span>{state.actionTitle}</span><span className={state.discovered ? "accent" : "muted"}>{state.actionTag}</span></div>
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
          {state.discovered ? <div className="quoted-total"><span>Quoted total · test pathUSD</span><span>{money(state.quotedTotal)}</span></div> : <div className="empty-state">Services appear after free live discovery.</div>}
        </section>

        <section aria-label="Balances" className="panel balances-panel">
          <div className="panel-heading"><h2>On-chain balances</h2><span>Tempo Moderato testnet</span></div>
          <div className="agent-balance">
            <span><span>Agent wallet</span><small>Separate from service budget</small></span>
            {state.agent?.wallet_balance?.explorer_url ? <a href={state.agent.wallet_balance.explorer_url} target="_blank" rel="noreferrer">{walletAmount(state.agent.wallet_balance)}</a> : <span>{walletAmount(state.agent?.wallet_balance)}</span>}
          </div>
          <div className="earnings-label">Provider earnings this session · on-chain wallet</div>
          {state.providers.map(provider => (
            <div key={provider.endpoint_id} className="provider-balance">
              <span><span>{provider.name}</span><small>+{money(provider.session_earned_cents)} test pathUSD</small></span>
              {provider.wallet_balance?.explorer_url ? <a href={provider.wallet_balance.explorer_url} target="_blank" rel="noreferrer">{walletAmount(provider.wallet_balance)}</a> : <span>{walletAmount(provider.wallet_balance)}</span>}
            </div>
          ))}
          <div className="platform-wallet"><span>OpenMCP wallet</span><span>{walletAmount(state.platform?.wallet_balance)}</span></div>
          <div className="platform-fees"><span>OpenMCP gross fees{state.feeRate === null ? "" : ` · ${state.feeRate}%`}</span><span>{money(state.fees)} test pathUSD</span></div>
        </section>

        <section aria-label="Payment record" className="panel ledger-panel">
          <div className="panel-heading"><h2>Payment record</h2><span className="mono">two MPP receipts per purchase</span></div>
          <div className="table-scroll ledger-scroll" role="region" aria-label="Payment details" tabIndex={0}>
            <div role="table" aria-label="Payment ledger" className="ledger-table">
              <div role="row" className="ledger-columns table-heading"><span role="columnheader">Request</span><span role="columnheader">Service</span><span role="columnheader" className="align-right">Charged</span><span role="columnheader" className="align-right">Provider</span><span role="columnheader" className="align-right">Fee</span></div>
              {state.ledger.map(row => (
                <div role="row" key={row.id} className={`ledger-columns ledger-row ${row.fresh ? "fresh-payment" : ""}`}>
                  <span role="cell" className="receipt-cell">
                    <span className="mono request-id" title={row.id}>{row.req}</span>
                    {row.incoming ? <a href={row.incoming.url} target="_blank" rel="noreferrer" title={row.incoming.reference}>Claude → OpenMCP · {shortReference(row.incoming.reference)}</a> : <span className="receipt-pending">Claude receipt pending</span>}
                    {row.outgoing ? <a href={row.outgoing.url} target="_blank" rel="noreferrer" title={row.outgoing.reference}>OpenMCP → provider · {shortReference(row.outgoing.reference)}</a> : <span className="receipt-pending">Provider receipt pending</span>}
                  </span>
                  <span role="cell"><span>{row.name}</span><small>{row.status.replaceAll("_", " ")}</small></span>
                  <span role="cell" className="align-right">{row.price === null ? "Pending" : money(row.price)}</span>
                  <span role="cell" className="align-right">{row.earned === null ? "Pending" : money(row.earned)}</span>
                  <span role="cell" className="align-right muted">{row.fee === null ? "Pending" : money(row.fee)}</span>
                </div>
              ))}
            </div>
            {state.ledger.length === 0 && <div className="empty-state">No payments yet. Verified testnet receipts appear here as each purchase settles.</div>}
            <div className="ledger-columns ledger-total"><span /><span className="muted">Total · test pathUSD</span><span className="align-right">{money(state.spent)}</span><span className="align-right">{money(state.providers.reduce((sum, provider) => sum + provider.session_earned_cents, 0))}</span><span className="align-right muted">{money(state.fees)}</span></div>
          </div>
        </section>

        <section aria-label="Report" className="panel report-panel">
          <div className="panel-heading"><h2>Report</h2><span>{state.complete ? "Complete" : `${deliveredCount} of ${state.rows.length || 3} sections`} · fictional evidence</span></div>
          <div className="report-body">
            {state.rows.map(report => (
              <div key={report.id} className="report-section">
                <div className="report-heading"><h3 className={report.delivered ? "" : "pending-title"}>{report.name}</h3><span>{report.delivered ? report.provider : "Pending"}</span></div>
                {report.delivered ? (
                  <>
                    {report.isDemoData && <span className="fictional-label">Fictional demo data</span>}
                    <p>{report.text ?? "Provider returned no narrative content."}</p>
                    {report.sources.length > 0 && (
                      <ul className="source-list" aria-label={`${report.name} sources`}>
                        {report.sources.map((source, index) => <li key={source.id ?? `${report.id}-${index}`}><span>{source.title ?? source.id ?? "Provider source"}</span>{source.publisher && <small>{source.publisher}</small>}</li>)}
                      </ul>
                    )}
                  </>
                ) : <div className="report-placeholder" aria-label="Awaiting service data"><span /><span /></div>}
              </div>
            ))}
            {!state.discovered && <div className="empty-state report-empty">Live provider sections appear after discovery.</div>}
            {state.complete && <div className="recommendation"><span>Completion summary</span><p>All three fictional provider reports arrived with two verified Tempo testnet payment receipts per source.</p></div>}
          </div>
        </section>
      </main>
    </div>
  );
}
