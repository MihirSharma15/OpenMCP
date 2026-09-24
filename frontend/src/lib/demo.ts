import type {
  PublicReceipt,
  RunnerState,
  Transaction,
  WalletBalance,
} from "@/lib/openmcp";

const SERVICE_LABELS: Record<string, string> = {
  "operational-health": "Operational health",
  "legal-liabilities": "Legal liabilities",
  "competitor-market-share": "Competitor market share",
};

export function money(cents: number): string {
  return (cents / 100).toFixed(2);
}

export function shortAddress(value: string | undefined): string {
  if (!value) return "Unavailable";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export function shortReference(value: string | undefined): string {
  if (!value) return "Pending";
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
}

export function walletAmount(balance: WalletBalance | undefined): string {
  if (!balance || balance.error) return "Unavailable";
  if (balance.balance) {
    const parsed = Number(balance.balance);
    return `${Number.isFinite(parsed) ? parsed.toFixed(2) : balance.balance} USD`;
  }
  if (typeof balance.balance_units === "number" && typeof balance.decimals === "number") {
    return `${(balance.balance_units / 10 ** balance.decimals).toFixed(2)} USD`;
  }
  return "Unavailable";
}

export function serviceLabel(endpointId: string): string {
  return (
    SERVICE_LABELS[endpointId] ??
    endpointId
      .split("-")
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}

export function serviceStatus(transaction: Transaction): string {
  switch (transaction.status) {
    case "payment_pending":
      return "Payment pending";
    case "provider_pending":
      return "Provider pending";
    case "completed":
      return "Completed";
    default:
      return "Quoted";
  }
}

function receiptLink(receipt: PublicReceipt | null) {
  if (!receipt?.explorer_url) return null;
  return {
    reference: receipt.reference,
    url: receipt.explorer_url,
  };
}

export function getDemoState(state: RunnerState | null) {
  const dashboard = state?.dashboard;
  const transactions = [...(dashboard?.transactions ?? [])].reverse();
  const rows = transactions.map(transaction => {
    const timestamp =
      transaction.openmcp_to_provider?.timestamp ?? transaction.agent_to_openmcp?.timestamp;
    const settledAt = timestamp ? Date.parse(timestamp) : Number.NaN;

    return {
      id: transaction.execution_id,
      provider: transaction.provider,
      service: serviceLabel(transaction.endpoint_id),
      endpointId: transaction.endpoint_id,
      charged: transaction.agent_to_openmcp ? transaction.price_cents : null,
      status: serviceStatus(transaction),
      statusKey: transaction.status.replaceAll("_", "-"),
      incoming: receiptLink(transaction.agent_to_openmcp),
      outgoing: receiptLink(transaction.openmcp_to_provider),
      fresh: Number.isFinite(settledAt) && Date.now() - settledAt < 2500,
    };
  });

  return {
    agent: dashboard?.agent,
    spent: dashboard?.agent.spent_cents ?? 0,
    reserved: dashboard?.agent.reserved_cents ?? 0,
    remaining: dashboard?.agent.remaining_cents ?? 0,
    budget: dashboard?.agent.budget_cents ?? 0,
    rows,
  };
}
