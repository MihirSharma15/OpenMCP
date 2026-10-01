"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { NumberTicker } from "@/components/magicui/number-ticker";
import {
  clampBudgetCents,
  DEFAULT_BUDGET_CENTS,
  formatBudgetInput,
  parseBudgetInput,
} from "@/lib/budget";
import {
  getDemoState,
  money,
  shortAddress,
  shortReference,
  walletAmount,
} from "@/lib/demo";
import {
  type DemoError,
  fetchRunnerState,
  resetDemo,
  RunnerApiError,
  type RunnerState,
  type WalletBalance,
} from "@/lib/openmcp";

function errorDetail(error: unknown): DemoError {
  if (error instanceof RunnerApiError) return error.detail;
  return {
    code: "demo_action_failed",
    message: "The budget change failed. Retry without changing the active session.",
    retryable: true,
  };
}

export default function Demo() {
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [walletBalance, setWalletBalance] = useState<WalletBalance | undefined>();
  const [budgetInput, setBudgetInput] = useState(formatBudgetInput(DEFAULT_BUDGET_CENTS));
  const [budgetInputError, setBudgetInputError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<DemoError | null>(null);
  const [actionError, setActionError] = useState<DemoError | null>(null);
  const [applying, setApplying] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const budgetSessionRef = useRef<string | null>(null);
  const nextChainPollRef = useRef(0);
  const generationRef = useRef(0);
  const state = getDemoState(runnerState);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let controller: AbortController | undefined;

    async function poll() {
      const includeChain = Date.now() >= nextChainPollRef.current;
      const generation = generationRef.current;
      controller = new AbortController();

      try {
        const next = await fetchRunnerState(includeChain, controller.signal);
        if (!active || generation !== generationRef.current) return;

        const sessionId = next.dashboard.agent.session_id;
        if (sessionRef.current !== null && sessionRef.current !== sessionId) {
          setWalletBalance(undefined);
          nextChainPollRef.current = 0;
        }
        sessionRef.current = sessionId;

        if (includeChain) {
          setWalletBalance(next.dashboard.agent.wallet_balance);
          nextChainPollRef.current = Date.now() + 5000;
        }
        if (budgetSessionRef.current !== sessionId) {
          const nextBudget = clampBudgetCents(next.dashboard.agent.budget_cents);
          setBudgetInput(formatBudgetInput(nextBudget));
          setBudgetInputError(null);
          budgetSessionRef.current = sessionId;
        }

        setRunnerState(next);
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

  async function applyBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);

    const parsed = parseBudgetInput(budgetInput);
    if (!parsed.valid) {
      setBudgetInputError(parsed.message);
      return;
    }

    setApplying(true);

    try {
      const nextSession = await resetDemo(parsed.cents);
      generationRef.current += 1;
      sessionRef.current = nextSession.session_id;
      budgetSessionRef.current = nextSession.session_id;
      nextChainPollRef.current = 0;
      const nextBudget = clampBudgetCents(nextSession.budget_cents);
      setBudgetInput(formatBudgetInput(nextBudget));
      setBudgetInputError(null);
      setWalletBalance(undefined);
      setRunnerState(previous =>
        previous
          ? {
              dashboard: {
                ...previous.dashboard,
                agent: {
                  ...previous.dashboard.agent,
                  ...nextSession,
                  wallet_balance: undefined,
                },
                transactions: [],
              },
            }
          : previous,
      );
    } catch (error) {
      setActionError(errorDetail(error));
    } finally {
      setApplying(false);
    }
  }

  function updateBudgetFromInput(value: string) {
    setBudgetInput(value);
    const parsed = parseBudgetInput(value);
    if (!parsed.valid) {
      setBudgetInputError(parsed.message);
      return;
    }
    setBudgetInputError(null);
  }

  function normalizeBudgetInput() {
    const parsed = parseBudgetInput(budgetInput);
    if (parsed.valid) {
      setBudgetInput(parsed.formatted);
    }
  }

  const visibleError = actionError ?? pollError;
  const offline =
    (pollError !== null && actionError === null) ||
    visibleError?.code === "runner_offline" ||
    visibleError?.code === "runner_unavailable" ||
    visibleError?.code === "gateway_unavailable";

  return (
    <div className="demo-page">
      <a href="#demo-main" className="skip-link">
        Skip to content
      </a>
      <header className="demo-header">
        <div className="demo-brand">
          <Link href="/" className="demo-wordmark">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M3 18V9a7 7 0 0 1 14 0v9" stroke="#161514" strokeWidth="1.6" />
              <path d="M8 18v-6a2 2 0 0 1 4 0v6" stroke="#6259A6" strokeWidth="1.6" />
            </svg>
            <span>OpenMCP</span>
          </Link>
          <span className="header-divider" />
          <span className="demo-subtitle">Wallet observer</span>
        </div>
        <div className="demo-controls">
          <Link href="/providers" className="provider-dashboard-link">
            Providers ↗
          </Link>
          <span
            className="test-mode"
            title="Real MPP transfers using valueless Tempo Moderato test tokens."
          >
            Tempo testnet · valueless tokens
          </span>
        </div>
      </header>

      <main id="demo-main" className="demo-grid">
        {visibleError && (
          <section
            className={`demo-banner ${offline ? "offline-banner" : "error-banner"}`}
            role="alert"
          >
            <strong>{offline ? "Local demo stack offline" : "Budget change failed"}</strong>
            <span>{visibleError.message}</span>
            {offline && <code>uv run python -m scripts.run_demo</code>}
          </section>
        )}

        <section aria-labelledby="balance-heading" className="panel balance-panel">
          <div className="panel-heading">
            <h1 id="balance-heading">Balance</h1>
          </div>
          <div className="balance-body">
            <div className="balance-amount">
              {state.agent ? (
                <NumberTicker
                  value={state.remaining / 100}
                  startValue={state.remaining / 100}
                  decimalPlaces={2}
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  aria-label={`${money(state.remaining)} USD remaining`}
                />
              ) : (
                <span aria-label="Remaining budget loading">—</span>
              )}
              <small aria-hidden={Boolean(state.agent)}>USD remaining</small>
            </div>
            <dl className="balance-summary">
              <div>
                <dt>Budget</dt>
                <dd>{state.agent ? money(state.budget) : "—"}</dd>
              </div>
              <div>
                <dt>Spent</dt>
                <dd>{state.agent ? money(state.spent) : "—"}</dd>
              </div>
            </dl>
          </div>
          <div className="wallet-line">
            <span>
              <strong>Wallet balance</strong>
              <small>
                Agent wallet ·{" "}
                <span className="mono" title={state.agent?.address}>
                  {shortAddress(state.agent?.address)}
                </span>
              </small>
            </span>
            {walletBalance?.explorer_url ? (
              <a href={walletBalance.explorer_url} target="_blank" rel="noreferrer">
                {walletAmount(walletBalance)}
              </a>
            ) : (
              <span>{walletAmount(walletBalance)}</span>
            )}
          </div>
        </section>

        <section aria-labelledby="budget-heading" className="panel budget-control-panel">
          <div className="panel-heading">
            <h2 id="budget-heading">Session budget</h2>
          </div>
          <form className="budget-form" onSubmit={applyBudget}>
            <div className="budget-input-row">
              <label htmlFor="budget-amount">Amount</label>
              <div className={`budget-input-shell ${budgetInputError ? "has-error" : ""}`}>
                <span aria-hidden="true">$</span>
                <input
                  id="budget-amount"
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  value={budgetInput}
                  onChange={event => updateBudgetFromInput(event.target.value)}
                  onBlur={normalizeBudgetInput}
                  disabled={!runnerState || applying}
                  aria-invalid={Boolean(budgetInputError)}
                  aria-describedby={budgetInputError ? "budget-input-error" : undefined}
                  aria-label="Session budget in USD"
                />
                <span>USD</span>
              </div>
            </div>
            {budgetInputError && (
              <p id="budget-input-error" className="budget-input-error" role="alert">
                {budgetInputError}
              </p>
            )}
            <button
              type="submit"
              className="button apply-button"
              disabled={!runnerState || applying || Boolean(budgetInputError)}
            >
              {applying ? "Applying…" : "Apply"}
            </button>
          </form>
        </section>

        <section aria-labelledby="transactions-heading" className="panel transactions-panel">
          <div className="panel-heading">
            <h2 id="transactions-heading">Recent transactions</h2>
            <span>{state.rows.length} {state.rows.length === 1 ? "transaction" : "transactions"}</span>
          </div>
          <div className="table-scroll" role="region" aria-label="Recent transaction details" tabIndex={0}>
            <table className="transactions-table">
              <thead>
                <tr>
                  <th scope="col">Provider</th>
                  <th scope="col">Endpoint / query type</th>
                  <th scope="col" className="align-right">Price · USD</th>
                  <th scope="col">State</th>
                  <th scope="col">Tempo receipts</th>
                </tr>
              </thead>
              <tbody>
                {state.rows.map(row => (
                  <tr key={row.id} className={row.fresh ? "fresh-payment" : undefined}>
                    <td>{row.provider}</td>
                    <td className="endpoint-cell">
                      <span>{row.service}</span>
                      <code>{row.endpointId}</code>
                    </td>
                    <td className="align-right">
                      {row.charged === null ? "Pending" : money(row.charged)}
                    </td>
                    <td>
                      <span className={`status status-${row.statusKey}`}>{row.status}</span>
                    </td>
                    <td className="receipt-cell">
                      {row.incoming ? (
                        <a
                          href={row.incoming.url}
                          target="_blank"
                          rel="noreferrer"
                          title={row.incoming.reference}
                        >
                          Claude to OpenMCP · {shortReference(row.incoming.reference)}
                        </a>
                      ) : (
                        <span>Claude receipt pending</span>
                      )}
                      {row.outgoing ? (
                        <a
                          href={row.outgoing.url}
                          target="_blank"
                          rel="noreferrer"
                          title={row.outgoing.reference}
                        >
                          OpenMCP to provider · {shortReference(row.outgoing.reference)}
                        </a>
                      ) : (
                        <span>Provider receipt pending</span>
                      )}
                    </td>
                  </tr>
                ))}
                {state.rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty-state">
                      No session transactions yet. Purchases made by Claude appear here with their
                      Tempo receipts.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
