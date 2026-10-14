"use client";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";

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
    message:
      "The budget change failed. Retry without changing the active session.",
    retryable: true,
  };
}

export default function Demo() {
  const [runnerState, setRunnerState] = useState<RunnerState | null>(null);
  const [walletBalance, setWalletBalance] = useState<
    WalletBalance | undefined
  >();
  const [budgetInput, setBudgetInput] = useState(
    formatBudgetInput(DEFAULT_BUDGET_CENTS),
  );
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
          const nextBudget = clampBudgetCents(
            next.dashboard.agent.budget_cents,
          );
          setBudgetInput(formatBudgetInput(nextBudget));
          setBudgetInputError(null);
          budgetSessionRef.current = sessionId;
        }

        setRunnerState(next);
        setPollError(null);
      } catch (error) {
        if (
          !active ||
          (error instanceof DOMException && error.name === "AbortError")
        )
          return;
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
      setRunnerState((previous) =>
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
  const parsedBudget = parseBudgetInput(budgetInput);
  const sliderValue = parsedBudget.valid
    ? parsedBudget.cents
    : DEFAULT_BUDGET_CENTS;
  const sliderMax = Math.max(10000, Math.ceil(sliderValue / 10000) * 10000);
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
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M3 18V9a7 7 0 0 1 14 0v9"
                stroke="#161514"
                strokeWidth="1.6"
              />
              <path
                d="M8 18v-6a2 2 0 0 1 4 0v6"
                stroke="#6259A6"
                strokeWidth="1.6"
              />
            </svg>
            <span>OpenMCP</span>
          </Link>
          <Separator orientation="vertical" className="header-divider" />
          <span className="demo-subtitle">Wallet observer</span>
        </div>
        <div className="demo-controls">
          <Link href="/providers" className="provider-dashboard-link">
            Providers ↗
          </Link>
          <Badge
            className="test-mode"
            title="Real MPP transfers using valueless Tempo Moderato test tokens."
          >
            Tempo testnet · valueless tokens
          </Badge>
        </div>
      </header>

      <main id="demo-main" className="demo-grid">
        {visibleError && (
          <section
            className={`demo-banner ${offline ? "offline-banner" : "error-banner"}`}
            role="alert"
          >
            <strong>
              {offline ? "Local demo stack offline" : "Budget change failed"}
            </strong>
            <span>{visibleError.message}</span>
            {offline && <code>uv run python -m scripts.run_demo</code>}
          </section>
        )}

        <Card
          as="section"
          aria-labelledby="balance-heading"
          className="panel balance-panel"
        >
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
              <a
                href={walletBalance.explorer_url}
                target="_blank"
                rel="noreferrer"
              >
                {walletAmount(walletBalance)}
              </a>
            ) : (
              <span>{walletAmount(walletBalance)}</span>
            )}
          </div>
        </Card>

        <Card
          as="section"
          aria-labelledby="budget-heading"
          className="panel budget-control-panel"
        >
          <div className="panel-heading">
            <h2 id="budget-heading">Session budget</h2>
          </div>
          <form className="budget-form" onSubmit={applyBudget}>
            <div className="budget-input-row">
              <Label htmlFor="budget-amount">Amount</Label>
              <div
                className={`budget-input-shell ${budgetInputError ? "has-error" : ""}`}
              >
                <span aria-hidden="true">$</span>
                <Input
                  variant="bare"
                  id="budget-amount"
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  value={budgetInput}
                  onChange={(event) =>
                    updateBudgetFromInput(event.target.value)
                  }
                  onBlur={normalizeBudgetInput}
                  disabled={!runnerState || applying}
                  aria-invalid={Boolean(budgetInputError)}
                  aria-describedby={
                    budgetInputError ? "budget-input-error" : undefined
                  }
                  aria-label="Session budget in USD"
                />
                <span>USD</span>
              </div>
            </div>
            <div className="budget-slider-control">
              <Slider
                aria-label="Session budget"
                aria-valuetext={`${money(sliderValue)} US dollars`}
                min={1}
                max={sliderMax}
                step={1}
                value={[Math.min(sliderValue, sliderMax)]}
                disabled={!runnerState || applying}
                onValueChange={([value]) =>
                  updateBudgetFromInput(formatBudgetInput(value))
                }
              />
              <div className="budget-slider-labels">
                <span>$0.01</span>
                <span>${money(sliderMax)}</span>
              </div>
              <p>
                Applying a budget starts a new session and clears its
                transaction history.
              </p>
            </div>
            {budgetInputError && (
              <p
                id="budget-input-error"
                className="budget-input-error"
                role="alert"
              >
                {budgetInputError}
              </p>
            )}
            <Button
              variant="default"
              type="submit"
              className="button apply-button"
              disabled={!runnerState || applying || Boolean(budgetInputError)}
            >
              {applying ? "Applying…" : "Apply"}
            </Button>
          </form>
        </Card>

        <Card
          as="section"
          aria-labelledby="transactions-heading"
          className="panel transactions-panel"
        >
          <div className="panel-heading">
            <h2 id="transactions-heading">Recent transactions</h2>
            <span>
              {state.rows.length}{" "}
              {state.rows.length === 1 ? "transaction" : "transactions"}
            </span>
          </div>
          <div
            className="table-scroll"
            role="region"
            aria-label="Recent transaction details"
            tabIndex={0}
          >
            <Table className="transactions-table">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Provider</TableHead>
                  <TableHead scope="col">Endpoint / query type</TableHead>
                  <TableHead scope="col" className="align-right">
                    Price · USD
                  </TableHead>
                  <TableHead scope="col">State</TableHead>
                  <TableHead scope="col">Tempo receipts</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {state.rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className={row.fresh ? "fresh-payment" : undefined}
                  >
                    <TableCell>{row.provider}</TableCell>
                    <TableCell className="endpoint-cell">
                      <span>{row.service}</span>
                      <code>{row.endpointId}</code>
                    </TableCell>
                    <TableCell className="align-right">
                      {row.charged === null ? "Pending" : money(row.charged)}
                    </TableCell>
                    <TableCell>
                      <Badge className={`status status-${row.statusKey}`}>
                        {row.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="receipt-cell">
                      {row.incoming ? (
                        <a
                          href={row.incoming.url}
                          target="_blank"
                          rel="noreferrer"
                          title={row.incoming.reference}
                        >
                          Claude to OpenMCP ·{" "}
                          {shortReference(row.incoming.reference)}
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
                          OpenMCP to provider ·{" "}
                          {shortReference(row.outgoing.reference)}
                        </a>
                      ) : (
                        <span>Provider receipt pending</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {state.rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="empty-state">
                      No session transactions yet. Purchases made by Claude
                      appear here with their Tempo receipts.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </Card>
      </main>
    </div>
  );
}
