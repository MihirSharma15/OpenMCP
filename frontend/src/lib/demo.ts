import type {
  DiscoveryEndpoint,
  GatewayEvent,
  PublicReceipt,
  RunnerState,
  Transaction,
  WalletBalance,
} from "@/lib/openmcp";

const SERVICE_ORDER: Record<string, number> = {
  "operational-health": 0,
  "legal-liabilities": 1,
  "competitor-market-share": 2,
};

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
    return `${Number.isFinite(parsed) ? parsed.toFixed(2) : balance.balance} ${balance.token ?? "pathUSD"}`;
  }
  if (typeof balance.balance_units === "number" && typeof balance.decimals === "number") {
    return `${(balance.balance_units / 10 ** balance.decimals).toFixed(2)} ${
      balance.token ?? "pathUSD"
    }`;
  }
  return "Unavailable";
}

function serviceLabel(endpointId: string): string {
  return (
    SERVICE_LABELS[endpointId] ??
    endpointId
      .split("-")
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}

function serviceStatus(transaction: Transaction | undefined) {
  switch (transaction?.status) {
    case "quoted":
    case "payment_pending":
      return "Paying";
    case "provider_pending":
      return "Receiving";
    case "completed":
      return "Delivered";
    default:
      return "Quoted";
  }
}

function eventAmount(event: GatewayEvent): number | null {
  const value =
    typeof event.detail.amount_cents === "number"
      ? event.detail.amount_cents
      : typeof event.detail.price_cents === "number"
        ? event.detail.price_cents
        : null;
  return value;
}

function latestEvent(events: GatewayEvent[]): GatewayEvent | undefined {
  return [...events].sort((left, right) => right.id - left.id)[0];
}

function actionFor(
  event: GatewayEvent | undefined,
  endpointName: string | undefined,
  complete: boolean,
  discoveredCount: number,
  quotedTotal: number,
) {
  if (complete) {
    return {
      stageIndex: 3,
      actionTitle: "Live report ready",
      actionTag: "Complete",
      actionCode: "All provider responses and both receipts per purchase are verified.",
    };
  }
  if (!event) {
    if (discoveredCount > 0) {
      return {
        stageIndex: 0,
        actionTitle: `${discoveredCount} paid services ready`,
        actionTag: "Quoted",
        actionCode: `Discovery is free · quoted total ${money(quotedTotal)} test pathUSD`,
      };
    }
    return {
      stageIndex: -1,
      actionTitle: "Waiting for the local agent",
      actionTag: "Ready",
      actionCode: "Run starts real MPP purchases with valueless Tempo testnet tokens.",
    };
  }

  const name = endpointName?.toLowerCase() ?? "the current service";
  const amount = eventAmount(event);
  const amountText = amount === null ? "" : ` · ${money(amount)} test pathUSD`;
  switch (event.type) {
    case "agent_challenge_created":
      return {
        stageIndex: 1,
        actionTitle: `OpenMCP quoted ${name}`,
        actionTag: "Paying",
        actionCode: `MPP challenge created${amountText}`,
      };
    case "agent_payment_submitted":
      return {
        stageIndex: 1,
        actionTitle: `Agent payment submitted for ${name}`,
        actionTag: "Verifying",
        actionCode: `Agent → OpenMCP credential submitted${amountText}`,
      };
    case "agent_payment_confirmed":
      return {
        stageIndex: 1,
        actionTitle: `Agent payment confirmed for ${name}`,
        actionTag: "Paid",
        actionCode: `Agent → OpenMCP settled${amountText}`,
      };
    case "provider_challenge_received":
      return {
        stageIndex: 2,
        actionTitle: `Provider requested payment for ${name}`,
        actionTag: "Receiving",
        actionCode: `OpenMCP received the provider's MPP challenge${amountText}`,
      };
    case "provider_credential_created":
      return {
        stageIndex: 2,
        actionTitle: `OpenMCP is paying for ${name}`,
        actionTag: "Paying provider",
        actionCode: `OpenMCP → provider payment authorized${amountText}`,
      };
    case "provider_payment_confirmed":
      return {
        stageIndex: 2,
        actionTitle: `Provider payment confirmed for ${name}`,
        actionTag: "Fulfilling",
        actionCode: `OpenMCP → provider settled${amountText}`,
      };
    case "completed":
      return {
        stageIndex: 2,
        actionTitle: `${endpointName ?? "Service"} delivered`,
        actionTag: "Delivered",
        actionCode: `Both MPP payments and provider data verified${amountText}`,
      };
    case "session_started":
      return {
        stageIndex: 0,
        actionTitle: "New service budget started",
        actionTag: "Reset",
        actionCode: "On-chain balances and earlier testnet transfers were not reversed.",
      };
    default:
      return {
        stageIndex: 1,
        actionTitle: `Processing ${name}`,
        actionTag: "Live",
        actionCode: event.type.replaceAll("_", " "),
      };
  }
}

function receiptLink(receipt: PublicReceipt | null) {
  return receipt?.reference && receipt.explorer_url
    ? { reference: receipt.reference, url: receipt.explorer_url }
    : null;
}

export function getDemoState(state: RunnerState | null) {
  const dashboard = state?.dashboard;
  const discovery = state?.discovery;
  const transactions = dashboard?.transactions ?? [];
  const transactionByEndpoint = new Map(
    transactions.map(transaction => [transaction.endpoint_id, transaction]),
  );
  const discoveredEndpoints = discovery?.endpoints ?? [];
  const fallbackEndpoints: DiscoveryEndpoint[] = transactions.map(transaction => ({
    endpoint_id: transaction.endpoint_id,
    provider: transaction.provider,
    description: "",
    price_cents: transaction.price_cents,
    provider_price_cents: transaction.provider_amount_cents,
    platform_fee_cents: transaction.platform_fee_cents,
    input_schema: {},
    currency: transaction.currency,
    payment_protocol: "MPP",
    payment_method: "tempo",
    chain_id: dashboard?.chain_id ?? 42431,
    token_address: "",
    execute_path: "/execute",
    pay_to: dashboard?.platform.address ?? "",
    provider_wallet:
      dashboard?.providers.find(provider => provider.endpoint_id === transaction.endpoint_id)
        ?.address ?? "",
    affordable: true,
    relevance: 0,
  }));
  const endpoints = (discoveredEndpoints.length > 0 ? discoveredEndpoints : fallbackEndpoints).sort(
    (left, right) =>
      (SERVICE_ORDER[left.endpoint_id] ?? 99) - (SERVICE_ORDER[right.endpoint_id] ?? 99),
  );
  const latest = latestEvent(state?.events ?? []);
  const completedEventIds = new Map(
    (state?.events ?? [])
      .filter(event => event.type === "completed" && event.execution_id)
      .map(event => [event.execution_id, event.created]),
  );
  const rows = endpoints.map(endpoint => {
    const transaction = transactionByEndpoint.get(endpoint.endpoint_id);
    const status = serviceStatus(transaction);
    const completedAt = transaction
      ? completedEventIds.get(transaction.execution_id)
      : undefined;
    return {
      id: endpoint.endpoint_id,
      name: serviceLabel(endpoint.endpoint_id),
      provider: endpoint.provider,
      endpoint: `${endpoint.execute_path} · ${endpoint.endpoint_id}`,
      price: endpoint.price_cents,
      providerAmount: endpoint.provider_price_cents,
      fee: endpoint.platform_fee_cents,
      status,
      delivered: status === "Delivered",
      fresh: completedAt !== undefined && Date.now() - completedAt * 1000 < 2500,
      active:
        state?.job.current_endpoint === endpoint.endpoint_id ||
        status === "Paying" ||
        status === "Receiving",
      transaction,
      text: transaction?.data?.content,
      title: transaction?.data?.title,
      sources: transaction?.data?.sources ?? [],
      isDemoData:
        transaction?.data?.is_demo_data === true ||
        transaction?.data?.sources?.some(source => source.fictional === true) === true,
    };
  });
  const complete = rows.length > 0 && rows.every(row => row.delivered);
  const endpointForLatest = latest?.execution_id
    ? transactions.find(transaction => transaction.execution_id === latest.execution_id)?.endpoint_id
    : state?.job.current_endpoint;
  const action = actionFor(
    latest,
    endpointForLatest ? serviceLabel(endpointForLatest) : undefined,
    complete,
    endpoints.length,
    discovery?.total_price_cents ?? endpoints.reduce((sum, endpoint) => sum + endpoint.price_cents, 0),
  );
  const ledger = [...transactions].reverse().map(transaction => ({
    id: transaction.execution_id,
    req: shortReference(transaction.execution_id),
    name: serviceLabel(transaction.endpoint_id),
    price: transaction.agent_to_openmcp ? transaction.price_cents : null,
    earned: transaction.openmcp_to_provider ? transaction.provider_amount_cents : null,
    fee: transaction.status === "completed" ? transaction.platform_fee_cents : null,
    status: transaction.status,
    incoming: receiptLink(transaction.agent_to_openmcp),
    outgoing: receiptLink(transaction.openmcp_to_provider),
    fresh:
      (completedEventIds.get(transaction.execution_id) ?? 0) * 1000 > Date.now() - 2500,
  }));
  const feeBasis = endpoints.reduce((sum, endpoint) => sum + endpoint.price_cents, 0);
  const feeTotal = endpoints.reduce((sum, endpoint) => sum + endpoint.platform_fee_cents, 0);
  const pending = transactions.find(transaction => transaction.status !== "completed");

  return {
    rows,
    ledger,
    providers: dashboard?.providers ?? [],
    agent: dashboard?.agent,
    platform: dashboard?.platform,
    spent: dashboard?.agent.spent_cents ?? 0,
    reserved: dashboard?.agent.reserved_cents ?? 0,
    remaining: dashboard?.agent.remaining_cents ?? 0,
    budget: dashboard?.agent.budget_cents ?? 0,
    fees: dashboard?.platform.session_gross_fee_cents ?? 0,
    feeRate: feeBasis > 0 ? Math.round((feeTotal / feeBasis) * 100) : null,
    quotedTotal:
      discovery?.total_price_cents ??
      endpoints.reduce((sum, endpoint) => sum + endpoint.price_cents, 0),
    discovered: endpoints.length > 0,
    complete,
    pending,
    ...action,
  };
}
