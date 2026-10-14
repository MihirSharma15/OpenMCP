"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CircleAlert,
  Info,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import {
  money,
  type Agent,
  type Page,
  type Transaction,
  type Wallet,
} from "@/lib/account";
import {
  canAgentSpend,
  filterActivity,
  hasCompletePeriod,
  spendingSummary,
  type SpendPeriod,
} from "@/lib/dashboard";
import {
  Empty,
  ErrorNotice,
  Loading,
  Status,
  TransactionTable,
} from "./common";

export type DashboardResource<T> = {
  data: T | null;
  loading: boolean;
  error?: unknown;
  reload: () => void;
};

function Metric({
  label,
  value,
  note,
  help,
  primary = false,
}: {
  label: string;
  value: string;
  note: string;
  help?: string;
  primary?: boolean;
}) {
  return (
    <div className={`dashboard-metric${primary ? " is-primary" : ""}`}>
      <div className="dashboard-metric-label">
        {label}
        {help && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`About ${label}`}
              >
                <Info size={13} />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-64">{help}</TooltipContent>
          </Tooltip>
        )}
      </div>
      <strong>{value}</strong>
      <span>{note}</span>
    </div>
  );
}

export function DashboardOverview({
  wallet,
  history,
  agents,
  now,
  onAddMoney,
  onRefresh,
  onViewTransaction,
  preview = false,
}: {
  wallet: DashboardResource<Wallet>;
  history: DashboardResource<Page<Transaction>>;
  agents: DashboardResource<Page<Agent>>;
  now: number;
  onAddMoney: () => void;
  onRefresh: () => void;
  onViewTransaction?: (transaction: Transaction) => void;
  preview?: boolean;
}) {
  const [period, setPeriod] = useState<SpendPeriod>(7);
  const [activityType, setActivityType] = useState("all");
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const rows = history.data?.items ?? [];
  const summary = useMemo(
    () => spendingSummary(history.data?.items ?? [], period, now),
    [history.data, period, now],
  );
  const complete = history.data
    ? hasCompletePeriod(history.data, period, now)
    : false;
  const activeAgents =
    agents.data?.items.filter((agent) => canAgentSpend(agent, now)) ?? [];
  const agentList = [...(agents.data?.items ?? [])]
    .sort(
      (a, b) => Number(canAgentSpend(b, now)) - Number(canAgentSpend(a, now)),
    )
    .slice(0, 3);
  const filtered = filterActivity(rows, activityType, search);
  const visible = filtered.slice(0, showAll ? 100 : 5);
  const review = rows.filter((row) => row.status === "needs_review");
  const firstRun =
    wallet.data &&
    wallet.data.spent_cents === 0 &&
    agents.data?.items.length === 0 &&
    !agents.data.next_cursor;
  const dateRange = `${summary.series[0].label} – ${summary.series.at(-1)?.label}`;
  return (
    <>
      <div className="account-page-heading dashboard-heading">
        <div>
          <h1>Overview</h1>
          <p>Your wallet, working.</p>
        </div>
        <div className="dashboard-heading-actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={onRefresh}
            aria-label="Refresh dashboard"
            disabled={wallet.loading || history.loading || agents.loading}
          >
            <RefreshCw size={14} />
            <span>Refresh</span>
          </Button>
          <Button size="sm" onClick={onAddMoney} disabled={!wallet.data}>
            <Plus size={15} />
            Add money
          </Button>
        </div>
      </div>
      {Boolean(wallet.error) && (
        <ErrorNotice error={wallet.error} retry={wallet.reload} />
      )}
      <section
        className="dashboard-metrics"
        aria-label="Current wallet snapshot"
      >
        <Metric
          primary
          label="Available balance"
          value={wallet.data ? money(wallet.data.available_cents) : "—"}
          note="USD credits · Ready to spend"
          help="Funds available now. Pending purchases are already excluded."
        />
        <Metric
          label="In flight"
          value={wallet.data ? money(wallet.data.reserved_cents) : "—"}
          note="Reserved for pending purchases"
          help="Held until a service completes or the funds are returned. Not counted as completed spending."
        />
        <Metric
          label="Total spent"
          value={wallet.data ? money(wallet.data.spent_cents) : "—"}
          note="All time · After service refunds"
        />
        <Metric
          label="Active agents"
          value={
            agents.data
              ? `${activeAgents.length}${agents.data.next_cursor ? "+" : ""}`
              : "—"
          }
          note={
            agents.data?.next_cursor
              ? "In the first 100 agents"
              : "With remaining allowances"
          }
          help="Unexpired, active agents with an allowance remaining. Actual spending is also limited by the shared wallet balance."
        />
      </section>
      {wallet.data && wallet.data.deficit_cents > 0 && (
        <div className="dashboard-attention" role="status">
          <CircleAlert size={17} />
          <div>
            <strong>Purchases are paused</strong>
            <span>
              A funding reversal left a {money(wallet.data.deficit_cents)}{" "}
              deficit.
            </span>
          </div>
          <Button size="sm" variant="outline" onClick={onAddMoney}>
            Add money
            <ArrowRight size={14} />
          </Button>
        </div>
      )}
      {review.length > 0 && (
        <div className="dashboard-attention" role="status">
          <CircleAlert size={17} />
          <div>
            <strong>
              {review.length} recent{" "}
              {review.length === 1 ? "purchase needs" : "purchases need"} review
            </strong>
            <span>
              Payment is uncertain. These purchases are not counted as completed
              spending.
            </span>
          </div>
          <Button asChild size="sm" variant="outline">
            <Link
              href={
                preview
                  ? "#activity"
                  : "/dashboard/transactions?status=needs_review"
              }
            >
              Review
              <ArrowRight size={14} />
            </Link>
          </Button>
        </div>
      )}
      {firstRun && (
        <section className="dashboard-onboarding">
          <div>
            <span className="dashboard-kicker">GET STARTED</span>
            <h2>Three steps to your first useful result.</h2>
          </div>
          <div className="dashboard-setup-steps">
            <Button variant="ghost" onClick={onAddMoney}>
              <span>
                {wallet.data && wallet.data.balance_cents > 0 ? (
                  <Check size={14} />
                ) : (
                  "1"
                )}
              </span>
              Fund your wallet
              <ArrowUpRight size={14} />
            </Button>
            <Button asChild variant="ghost">
              <Link href="/dashboard/agents">
                <span>2</span>Create an agent
                <ArrowUpRight size={14} />
              </Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/dashboard/agents#connect">
                <span>3</span>Connect your LLM
                <ArrowUpRight size={14} />
              </Link>
            </Button>
          </div>
        </section>
      )}
      <div className="dashboard-insights">
        <Card as="section" className="dashboard-spending">
          <div className="dashboard-section-heading">
            <h2>Spending activity</h2>
            <ToggleGroup
              type="single"
              value={String(period)}
              onValueChange={(value) => {
                if (value) setPeriod(Number(value) as SpendPeriod);
              }}
              size="sm"
              className="dashboard-period"
              aria-label="Spending period"
            >
              <ToggleGroupItem value="7">7 days</ToggleGroupItem>
              <ToggleGroupItem value="30">30 days</ToggleGroupItem>
            </ToggleGroup>
          </div>
          {Boolean(history.error) && (
            <ErrorNotice error={history.error} retry={history.reload} />
          )}
          {history.loading ? (
            <Loading text="Loading spending activity…" />
          ) : (
            history.data && (
              <>
                <div className="dashboard-chart-stat">
                  <strong>{money(summary.cents)}</strong>
                  <div>
                    <span>
                      {summary.purchases} completed{" "}
                      {summary.purchases === 1 ? "purchase" : "purchases"}
                    </span>
                    <small>{dateRange}</small>
                  </div>
                </div>
                <ChartContainer
                  config={{
                    cents: {
                      label: "Completed spending",
                      color: "var(--violet)",
                    },
                  }}
                  className="dashboard-chart"
                  aria-label={`Completed purchase spending, ${dateRange}: ${money(summary.cents)}. ${complete ? "" : "Partial history."}`}
                >
                  <AreaChart
                    accessibilityLayer
                    data={summary.series}
                    margin={{ top: 8, right: 2, left: -17, bottom: 0 }}
                  >
                    <CartesianGrid
                      vertical={false}
                      stroke="var(--line)"
                      strokeDasharray="3 4"
                    />
                    <XAxis
                      dataKey="label"
                      axisLine={false}
                      tickLine={false}
                      minTickGap={38}
                      tickMargin={12}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      width={58}
                      tickFormatter={(value) => money(value)}
                      domain={[
                        0,
                        (max: number) =>
                          Math.max(100, Math.ceil(max / 100) * 100),
                      ]}
                      tickCount={4}
                    />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          formatter={(value) => (
                            <span className="font-mono">
                              {money(Number(value))}
                            </span>
                          )}
                        />
                      }
                    />
                    <Area
                      dataKey="cents"
                      type="linear"
                      stroke="var(--violet)"
                      strokeWidth={2}
                      fill="var(--tint)"
                      fillOpacity={0.65}
                      dot={false}
                      activeDot={{ r: 4 }}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ChartContainer>
                <div className="dashboard-chart-note">
                  <span>
                    <i />
                    Completed spending
                  </span>
                  <span>
                    {summary.purchases
                      ? "Excludes pending & refunded purchases"
                      : "No completed purchases in this period"}
                  </span>
                </div>
                {!complete && (
                  <p className="dashboard-partial" role="status">
                    Partial history · Based on the latest {rows.length}{" "}
                    transactions, not the full period.{" "}
                    <Link href="/dashboard/transactions">
                      View ledger <ArrowUpRight size={12} />
                    </Link>
                  </p>
                )}
              </>
            )
          )}
        </Card>
        <Card as="section" id="agents" className="dashboard-agents">
          <div className="dashboard-section-heading">
            <h2>Agent allowances</h2>
            <Button asChild variant="ghost" size="icon-xs">
              <Link href="/dashboard/agents" aria-label="Manage all agents">
                <ArrowUpRight size={16} />
              </Link>
            </Button>
          </div>
          <p className="dashboard-section-subtitle">
            Individual limits. One shared wallet.
          </p>
          {Boolean(agents.error) && (
            <ErrorNotice error={agents.error} retry={agents.reload} />
          )}
          {agents.loading ? (
            <Loading text="Loading agent allowances…" />
          ) : (
            agents.data &&
            (agentList.length ? (
              <div className="dashboard-agent-list">
                {agentList.map((agent) => (
                  <div key={agent.agent_id} className="dashboard-agent-row">
                    <div className="dashboard-agent-title">
                      <Bot size={16} />
                      <Link
                        href={`/dashboard/agents#agent-${encodeURIComponent(agent.agent_id)}`}
                      >
                        {agent.name}
                      </Link>
                      <Status value={agent.status} />
                    </div>
                    <div className="dashboard-agent-amount">
                      <strong>
                        {money(agent.remaining_cents)}
                        <span> left</span>
                      </strong>
                      <span>of {money(agent.spend_limit_cents)}</span>
                    </div>
                    <Progress
                      value={Math.min(
                        agent.spent_cents + agent.reserved_cents,
                        agent.spend_limit_cents,
                      )}
                      max={agent.spend_limit_cents}
                      aria-label={`${agent.name} allowance used`}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="dashboard-no-agents">
                <Bot size={26} strokeWidth={1.3} />
                <h3>A little direction goes a long way.</h3>
                <p>Create an agent and set exactly what it can spend.</p>
                <Button asChild variant="outline" size="sm">
                  <Link href="/dashboard/agents">
                    <Plus size={14} />
                    Create an agent
                  </Link>
                </Button>
              </div>
            ))
          )}
          <div className="dashboard-agent-footer">
            <ShieldCheck size={15} />
            <p>
              Allowances don’t reserve funds. Agents can only spend what’s
              available in your wallet.
            </p>
          </div>
        </Card>
      </div>
      <Card as="section" id="activity" className="dashboard-activity">
        <div className="dashboard-section-heading">
          <div>
            <h2>Recent activity</h2>
            <p className="dashboard-section-subtitle">
              The story behind every cent.
            </p>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link href="/dashboard/transactions">
              View ledger
              <ArrowUpRight size={14} />
            </Link>
          </Button>
        </div>
        <Tabs
          className="gap-0"
          value={activityType}
          onValueChange={(value) => {
            setActivityType(value);
            setShowAll(false);
          }}
        >
          <div className="dashboard-activity-toolbar">
            <TabsList variant="line" aria-label="Recent transaction type">
              {[
                ["all", "All activity"],
                ["purchase", "Purchases"],
                ["deposit", "Deposits"],
                ["refund", "Refunds"],
              ].map(([value, label]) => (
                <TabsTrigger value={value} key={value}>
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
            <div className="dashboard-activity-search">
              <Search size={14} />
              <Input
                variant="bare"
                aria-label="Search recent activity"
                placeholder="Search recent activity…"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setShowAll(false);
                }}
              />
            </div>
          </div>
          <TabsContent value={activityType}>
            {Boolean(history.error) && (
              <ErrorNotice error={history.error} retry={history.reload} />
            )}
            {history.loading ? (
              <Loading text="Loading recent activity…" />
            ) : (
              history.data &&
              (visible.length ? (
                <TransactionTable rows={visible} onView={onViewTransaction} />
              ) : (
                <Empty
                  title={
                    search || activityType !== "all"
                      ? "No matching activity"
                      : "Your first transaction starts here"
                  }
                >
                  <p>
                    {search || activityType !== "all"
                      ? "Try a different search or transaction type."
                      : "Add funds or let your agent make a purchase. Every deposit, purchase, and refund will appear here."}
                  </p>
                </Empty>
              ))
            )}
            {history.data && (
              <div className="dashboard-activity-footer">
                <span>
                  {filtered.length
                    ? `${visible.length} of ${filtered.length} matching transactions`
                    : "No transactions to show"}
                  {history.data.next_cursor
                    ? ` · Latest ${rows.length} loaded`
                    : ""}
                </span>
                {filtered.length > 5 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowAll((value) => !value)}
                  >
                    {showAll ? "Show fewer" : "Show more"}
                  </Button>
                )}
                <span>Times shown in your timezone</span>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </Card>
    </>
  );
}
