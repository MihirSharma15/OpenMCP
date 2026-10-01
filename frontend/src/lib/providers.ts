import type { ProviderOverview, ProviderTransaction } from "./openmcp";

export type ProviderView = "overview" | "payments" | "services" | "wallets";
export type Period = "7" | "30" | "all";
export type PaymentFilter = "all" | "received" | "pending";

export function isReceived(transaction: ProviderTransaction): boolean {
  return transaction.openmcp_to_provider?.status === "success" &&
    Boolean(transaction.openmcp_to_provider.reference);
}

export function paymentTime(transaction: ProviderTransaction): number {
  const receiptTime = Date.parse(transaction.openmcp_to_provider?.timestamp ?? "");
  return transaction.paid_at ?? (Number.isFinite(receiptTime) ? receiptTime / 1000 : transaction.created_at);
}

export function periodStart(period: Period, now: number): number {
  if (period === "all") return 0;
  const date = new Date(now);
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - Number(period) + 1);
  return date.getTime() / 1000;
}

export function scopedTransactions(data: ProviderOverview | null, provider: string, period: Period, now: number) {
  const start = periodStart(period, now);
  return (data?.transactions ?? [])
    .filter(transaction => (provider === "all" || transaction.endpoint_id === provider) && paymentTime(transaction) >= start)
    .sort((a, b) => paymentTime(b) - paymentTime(a));
}

export function paymentLabel(transaction: ProviderTransaction): string {
  if (isReceived(transaction)) return "Received";
  if (transaction.status === "quoted") return "Awaiting payment";
  return "Pending";
}

export function earningsSeries(transactions: ProviderTransaction[], period: Period, now: number) {
  const received = transactions.filter(isReceived);
  const end = new Date(now);
  end.setHours(0, 0, 0, 0);
  const start = new Date(period === "all"
    ? Math.min(end.getTime(), ...received.map(transaction => paymentTime(transaction) * 1000))
    : periodStart(period, now) * 1000);
  start.setHours(0, 0, 0, 0);
  // Keep even the first day legible. Longer histories are grouped into <= 30 buckets.
  if (period === "all" && start.getTime() === end.getTime()) start.setDate(start.getDate() - 6);
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
  const bucketDays = Math.max(1, Math.ceil(days / 30));
  const buckets: { start: number; end: number; label: string; cents: number }[] = [];
  for (const day = new Date(start); day <= end; day.setDate(day.getDate() + bucketDays)) {
    const next = new Date(day);
    next.setDate(next.getDate() + bucketDays);
    buckets.push({
      start: day.getTime() / 1000,
      end: next.getTime() / 1000,
      label: day.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      cents: 0,
    });
  }
  for (const transaction of received) {
    const time = paymentTime(transaction);
    const bucket = buckets.find(item => time >= item.start && time < item.end);
    if (bucket) bucket.cents += transaction.provider_amount_cents;
  }
  return buckets;
}

export function paymentsCsv(transactions: ProviderTransaction[]): string {
  const rows = [
    ["Execution ID", "Provider", "Endpoint", "Date (UTC)", "Status", "Agent paid (USD)", "Platform fee (USD)", "Provider received (USD)", "Provider receipt", "Agent receipt"],
    ...transactions.map(transaction => [
      transaction.execution_id, transaction.provider, transaction.endpoint_id,
      new Date(paymentTime(transaction) * 1000).toISOString(), paymentLabel(transaction),
      transaction.agent_to_openmcp?.status === "success" ? (transaction.price_cents / 100).toFixed(2) : "",
      isReceived(transaction) ? (transaction.platform_fee_cents / 100).toFixed(2) : "",
      isReceived(transaction) ? (transaction.provider_amount_cents / 100).toFixed(2) : "",
      transaction.openmcp_to_provider?.reference ?? "", transaction.agent_to_openmcp?.reference ?? "",
    ]),
  ];
  return rows.map(row => row.map(value => {
    // Neutralize spreadsheet formula prefixes in provider-controlled labels.
    const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  }).join(",")).join("\r\n");
}
