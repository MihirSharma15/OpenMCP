export type ExecutionStatus = "quoted" | "payment_pending" | "provider_pending" | "completed";

export interface DemoError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface WalletBalance {
  source: string;
  address?: string;
  token?: string;
  token_address?: string;
  chain_id?: number;
  balance_units?: number;
  decimals?: number;
  balance?: string;
  explorer_url?: string;
  error?: string;
}

export interface SessionBalance {
  session_id: string;
  currency: string;
  source: string;
  budget_cents: number;
  spent_cents: number;
  reserved_cents: number;
  remaining_cents: number;
}

export interface AgentDashboard extends SessionBalance {
  address: string;
  wallet_balance?: WalletBalance;
}

export interface PublicReceipt {
  method?: string;
  status?: string;
  reference?: string;
  chain_id?: number;
  timestamp?: string;
  explorer_url?: string;
}

export interface Transaction {
  execution_id: string;
  session_id: string;
  status: ExecutionStatus;
  endpoint_id: string;
  provider: string;
  currency: string;
  price_cents: number;
  agent_to_openmcp: PublicReceipt | null;
  openmcp_to_provider: PublicReceipt | null;
  error: DemoError | null;
}

export interface Dashboard {
  agent: AgentDashboard;
  transactions: Transaction[];
  payment_mode: string;
  currency: string;
  chain_id: number;
}

export interface RunnerState {
  dashboard: Dashboard;
}

export class RunnerApiError extends Error {
  readonly status: number;
  readonly detail: DemoError;

  constructor(status: number, detail: DemoError) {
    super(detail.message);
    this.name = "RunnerApiError";
    this.status = status;
    this.detail = detail;
  }
}

const API_ROOT = "/api/runner";
const DEMO_HEADERS = {
  "Content-Type": "application/json",
  "X-OpenMCP-Demo": "1",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      cache: "no-store",
      ...init,
      headers: { ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new RunnerApiError(503, {
      code: "runner_offline",
      message: "The local demo stack is offline. Start it with `uv run python -m scripts.run_demo`.",
      retryable: true,
    });
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const shaped =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error !== null
        ? (payload.error as DemoError)
        : null;
    if (shaped) throw new RunnerApiError(response.status, shaped);
    if (response.status >= 500) {
      throw new RunnerApiError(503, {
        code: "runner_offline",
        message:
          "The local demo stack is offline. Start it with `uv run python -m scripts.run_demo`.",
        retryable: true,
      });
    }
    throw new RunnerApiError(response.status, {
      code: "runner_http_error",
      message: `Demo runner returned HTTP ${response.status}.`,
      retryable: response.status >= 500,
    });
  }
  return payload as T;
}

function mutate<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: DEMO_HEADERS,
    body: JSON.stringify(body),
  });
}

export function fetchRunnerState(
  includeChain: boolean,
  signal?: AbortSignal,
): Promise<RunnerState> {
  const query = new URLSearchParams({
    chain: includeChain ? "1" : "0",
  });
  return request<RunnerState>(`/state?${query}`, { signal });
}

export function resetDemo(budgetCents: number): Promise<SessionBalance> {
  return mutate<SessionBalance>("/reset", { budget_cents: budgetCents });
}
