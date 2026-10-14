"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { DashboardFrame } from "@/components/account/dashboard-frame";
import {
  DashboardOverview,
  type DashboardResource,
} from "@/components/account/dashboard-overview";
import { AddMoneyDialog } from "@/components/account/top-up";
import { Modal, Status } from "@/components/account/common";
import { SelectField } from "@/components/select-field";
import {
  money,
  localDate,
  type Agent,
  type Transaction,
  type Wallet,
} from "@/lib/account";

function sampleWorkspace(now: number) {
  const names = ["Research assistant", "Market monitor", "Content explorer"];
  const descriptions = [
    "Web search",
    "Wallet analytics",
    "Page extraction",
    "Company research",
  ];
  const values = [
    28, 146, 82, 215, 56, 172, 91, 243, 128, 75, 190, 142, 65, 202, 48, 90, 260,
    112, 85, 164, 42, 238, 70, 156, 96, 275, 110, 190, 84, 132,
  ];
  const transactions: Transaction[] = values.map((cents, index) => {
    const date = new Date(now);
    date.setDate(date.getDate() - 29 + index);
    if (index !== values.length - 1) date.setHours(12, 30, 0, 0);
    return {
      id: `sample_purchase_${index}`,
      type: "purchase",
      status: "completed",
      amount_cents: -cents,
      currency: "usd_credits",
      description: descriptions[index % 4],
      created_at: date.toISOString(),
      balance_after_cents: null,
      agent_id: `sample_agent_${index % 3}`,
      agent_name: names[index % 3],
      endpoint_id: null,
      execution_id: null,
      related_transaction_id: null,
      receipt_url: null,
    };
  });
  const spent = values.reduce((sum, cents) => sum + cents, 0);
  const pending: Transaction = {
    ...transactions.at(-1)!,
    id: "sample_pending",
    status: "pending",
    amount_cents: -180,
    description: "Company research",
    created_at: new Date(now - 60_000).toISOString(),
  };
  const deposit: Transaction = {
    ...pending,
    id: "sample_deposit",
    type: "deposit",
    status: "completed",
    amount_cents: 5000,
    description: "Wallet top-up",
    agent_id: null,
    agent_name: null,
    created_at: new Date(now - 2 * 86400_000).toISOString(),
  };
  const refund: Transaction = {
    ...pending,
    id: "sample_refund",
    type: "refund",
    status: "completed",
    amount_cents: 50,
    description: "Service failure: credits returned",
    created_at: new Date(now - 86400_000).toISOString(),
  };
  const returned: Transaction = {
    ...refund,
    id: "sample_returned",
    type: "purchase",
    status: "refunded",
    amount_cents: -50,
    description: "Page extraction",
    created_at: new Date(now - 86400_000 - 60_000).toISOString(),
  };
  const opening: Transaction = {
    ...deposit,
    id: "sample_opening",
    created_at: new Date(now - 31 * 86400_000).toISOString(),
  };
  const agents: Agent[] = names.map((name, index) => {
    const limit = [5000, 3500, 2500][index];
    const agentSpent = transactions
      .filter((row) => row.agent_id === `sample_agent_${index}`)
      .reduce((sum, row) => sum - row.amount_cents, 0);
    const reserved = index === 2 ? 180 : 0;
    return {
      agent_id: `sample_agent_${index}`,
      name,
      spend_limit_cents: limit,
      spent_cents: agentSpent,
      reserved_cents: reserved,
      remaining_cents: limit - agentSpent - reserved,
      expires_at: new Date(now + 14 * 86400_000).toISOString(),
      status: "active",
      credentials: [],
    };
  });
  const wallet: Wallet = {
    account_id: "sample_workspace",
    balance_cents: 10000 - spent,
    available_cents: 10000 - spent - 180,
    reserved_cents: 180,
    deficit_cents: 0,
    spent_cents: spent,
    currency: "usd_credits",
    status: "active",
  };
  return {
    wallet,
    agents,
    transactions: [
      ...transactions,
      pending,
      deposit,
      refund,
      returned,
      opening,
    ].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  };
}

export default function DashboardPreview({ now }: { now: number }) {
  const sample = useMemo(() => sampleWorkspace(now), [now]);
  const [scenario, setScenario] = useState("active");
  const [topUp, setTopUp] = useState(false);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const empty = scenario === "new";
  const failed = scenario === "unavailable";
  const wallet = empty
    ? {
        ...sample.wallet,
        balance_cents: 0,
        available_cents: 0,
        reserved_cents: 0,
        spent_cents: 0,
      }
    : sample.wallet;
  const rows = empty
    ? []
    : scenario === "attention"
      ? sample.transactions.map((row) =>
          row.id === "sample_pending"
            ? { ...row, status: "needs_review" as const }
            : row,
        )
      : sample.transactions;
  const refresh = () =>
    toast("Preview refreshed", {
      description:
        "Illustrative data only. Your real account was not accessed.",
    });
  function resource<T>(data: T): DashboardResource<T> {
    return {
      data: failed ? null : data,
      loading: false,
      error: failed
        ? new Error(
            "Sample offline state. The account service could not be reached.",
          )
        : null,
      reload: refresh,
    };
  }
  return (
    <DashboardFrame preview>
      <div className="dashboard-preview-toolbar">
        <span>
          <strong>Design preview</strong> · Illustrative data. No real funds or
          account changes.
        </span>
        <SelectField
          label="Preview scenario"
          value={scenario}
          onValueChange={setScenario}
          options={[
            { value: "active", label: "Active workspace" },
            { value: "new", label: "New workspace" },
            { value: "attention", label: "Needs attention" },
            { value: "unavailable", label: "Service unavailable" },
            { value: "partial", label: "Partial history" },
          ]}
        />
      </div>
      <DashboardOverview
        key={scenario}
        preview
        wallet={resource(wallet)}
        history={resource({
          items: scenario === "partial" ? rows.slice(0, 4) : rows,
          next_cursor: scenario === "partial" ? "sample_cursor" : null,
        })}
        agents={resource({
          items: empty ? [] : sample.agents,
          next_cursor: null,
        })}
        now={now}
        onAddMoney={() => setTopUp(true)}
        onRefresh={refresh}
        onViewTransaction={setSelected}
      />
      {topUp && (
        <AddMoneyDialog
          presets={[500, 1000, 2500, 5000]}
          mode="test"
          onClose={() => setTopUp(false)}
          onCheckout={(amount) => {
            setTopUp(false);
            toast(`${money(amount)} selected`, {
              description:
                "Preview only. No checkout was created and no money was moved.",
            });
          }}
        />
      )}
      {selected && (
        <Modal title="Transaction preview" onClose={() => setSelected(null)}>
          <p className="account-dialog-copy">
            Illustrative transaction. This is not a real receipt.
          </p>
          <div className="account-return-amount">
            <span>{selected.description}</span>
            <strong>{money(selected.amount_cents)}</strong>
          </div>
          <dl className="account-detail-grid">
            <div>
              <dt>Status</dt>
              <dd>
                <Status value={selected.status} />
              </dd>
            </div>
            <div>
              <dt>Date</dt>
              <dd>{localDate(selected.created_at)}</dd>
            </div>
            <div>
              <dt>Agent</dt>
              <dd>{selected.agent_name ?? "—"}</dd>
            </div>
            <div>
              <dt>Reference</dt>
              <dd>{selected.id}</dd>
            </div>
          </dl>
        </Modal>
      )}
    </DashboardFrame>
  );
}
