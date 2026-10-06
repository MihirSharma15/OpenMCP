/** Account product contract. Keep aligned with docs/mvp-api-contract.json. */
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Account = {
  account_id: string; status: string; currency: "usd_credits";
  top_up_presets_cents: number[]; mode: "test" | "live";
};
export type Wallet = {
  account_id: string; balance_cents: number; available_cents: number;
  reserved_cents: number; deficit_cents: number; spent_cents: number;
  currency: "usd_credits"; status: string;
};
export type TopUp = {
  id: string; amount_cents: number; currency: "usd";
  status: "creating" | "awaiting_payment" | "processing" | "credited" | "failed" | "expired";
  checkout_url: string | null; expires_at: string | null; credited_at: string | null;
};
export type CredentialMetadata = {
  credential_id: string; created_at: string; expires_at: string; revoked: boolean;
};
export type Agent = {
  agent_id: string; name: string; spend_limit_cents: number; spent_cents: number;
  reserved_cents: number; remaining_cents: number; expires_at: string;
  status: "active" | "exhausted" | "expired" | "revoked";
  credentials: CredentialMetadata[];
};
export type Credential = { agent_id: string; credential_id: string; secret: string; expires_at: string };
export type Transaction = {
  id: string; type: "deposit" | "purchase" | "refund" | "reversal";
  status: "pending" | "completed" | "failed" | "refunded" | "needs_review";
  amount_cents: number; currency: "usd_credits"; description: string; created_at: string;
  balance_after_cents: number | null; agent_id: string | null; agent_name: string | null;
  endpoint_id: string | null; execution_id: string | null; related_transaction_id: string | null;
  receipt_url: string | null;
};
export type Execution = {
  execution_id: string; endpoint_id: string;
  status: "reserved" | "payment_pending" | "fulfillment_pending" | "completed" | "failed" | "refunded" | "needs_review";
  price_cents: number; charged_cents: number; refunded_cents: number; currency: "usd_credits";
  data: unknown; provider_receipt: { reference?: string; explorer_url?: string } | null;
  ledger_transaction_id: string | null; error: { message?: string; code?: string } | null;
  status_url: string; created_at: string;
};

export class AccountApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly requestId?: string;
  constructor(message: string, status = 0, code = "connection_error", retryable = true, requestId?: string) {
    super(message); this.name = "AccountApiError"; this.status = status;
    this.code = code; this.retryable = retryable; this.requestId = requestId;
  }
}

export async function accountRequest<T>(path: string, options: { method?: "GET" | "POST"; body?: unknown; key?: string; signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/openmcp${path}`, {
      method: options.method ?? "GET", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options.key ? { "Idempotency-Key": options.key } : {}) },
      body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: options.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new AccountApiError("Could not reach OpenMCP. Check your connection and retry.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new AccountApiError(data?.error?.message ?? "OpenMCP could not complete this request.", response.status,
      data?.error?.code ?? "request_failed", data?.error?.retryable ?? response.status >= 500, data?.request_id);
  }
  if (data === null) throw new AccountApiError("The server returned an unreadable response.", 502, "invalid_response");
  return data as T;
}

export function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}
export function localDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
export function safeExternalUrl(value: string | null | undefined, checkout = false): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (checkout && url.hostname !== "checkout.stripe.com") return null;
    return url.href;
  } catch { return null; }
}
export function parseAllowance(value: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value.trim())) return null;
  const [dollars, fraction = ""] = value.trim().split(".");
  const cents = Number(dollars) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(cents) && cents > 0 && cents <= 1_000_000 ? cents : null;
}
// Keep these bounds aligned with TopUpInput in the account API.
export const TOP_UP_MIN_CENTS = 100;
export const TOP_UP_MAX_CENTS = 5000;
export function parseTopUpAmount(value: string): number | null {
  const cents = parseAllowance(value);
  return cents !== null && cents >= TOP_UP_MIN_CENTS && cents <= TOP_UP_MAX_CENTS ? cents : null;
}
export function topUpPending(status: TopUp["status"]): boolean {
  return ["creating", "awaiting_payment", "processing"].includes(status);
}
export function clearCheckoutIntent(status: TopUp["status"]): boolean {
  return ["credited", "failed", "expired"].includes(status);
}
export const statusLabels: Record<string, string> = {
  pending: "Pending", completed: "Completed", failed: "Failed", refunded: "Refunded", needs_review: "Under review",
  active: "Active", exhausted: "Allowance used", expired: "Expired", revoked: "Revoked", restricted: "Restricted",
  creating: "Preparing checkout", awaiting_payment: "Awaiting payment", processing: "Confirming payment", credited: "Funds added",
  reserved: "Reserved", payment_pending: "Payment pending", fulfillment_pending: "Result pending",
};
export const transactionLabels: Record<Transaction["type"], string> = {
  deposit: "Money added", purchase: "Service purchase", refund: "Service refund", reversal: "Funding reversal",
};

// A new intended amount gets a new key; a failed network attempt keeps its key.
export type CheckoutIntent = { amount: number; key: string; topUpId?: string };
export function checkoutIntent(previous: CheckoutIntent | null, amount: number, uuid: () => string = () => crypto.randomUUID()): CheckoutIntent {
  return previous?.amount === amount ? previous : { amount, key: uuid() };
}
export function readCheckoutIntent(value: string | null): CheckoutIntent | null {
  try {
    const saved = JSON.parse(value ?? "null");
    if (!saved || !Number.isSafeInteger(saved.amount) || saved.amount <= 0 || typeof saved.key !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(saved.key)) return null;
    return { amount: saved.amount, key: saved.key, ...(typeof saved.topUpId === "string" ? { topUpId: saved.topUpId } : {}) };
  } catch { return null; }
}
export function returnedCheckoutMatches(intent: CheckoutIntent | null, topUp: Pick<TopUp, "id" | "status">): boolean {
  return Boolean(intent?.topUpId === topUp.id && clearCheckoutIntent(topUp.status));
}
