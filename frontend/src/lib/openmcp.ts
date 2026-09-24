export type ExecutionStatus = "quoted" | "payment_pending" | "provider_pending" | "completed";
export type JobStatus = "idle" | "running" | "pausing";

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

export interface AgentDashboard {
  address: string;
  session_id: string;
  currency: string;
  source: string;
  budget_cents: number;
  spent_cents: number;
  reserved_cents: number;
  remaining_cents: number;
  wallet_balance?: WalletBalance;
}

export interface PlatformDashboard {
  address: string;
  session_gross_fee_cents: number;
  wallet_balance?: WalletBalance;
}

export interface ProviderDashboard {
  endpoint_id: string;
  name: string;
  address: string;
  session_earned_cents: number;
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

export interface ReportSource {
  id?: string;
  title?: string;
  publisher?: string;
  fictional?: boolean;
  [key: string]: unknown;
}

export interface ProviderData {
  company?: string;
  provider?: string;
  title?: string;
  content?: string;
  metrics?: Record<string, unknown>;
  sources?: ReportSource[];
  is_demo_data?: boolean;
  [key: string]: unknown;
}

export interface Transaction {
  execution_id: string;
  session_id: string;
  status: ExecutionStatus;
  endpoint_id: string;
  provider: string;
  currency: string;
  price_cents: number;
  platform_fee_cents: number;
  provider_amount_cents: number;
  agent_to_openmcp: PublicReceipt | null;
  openmcp_to_provider: PublicReceipt | null;
  data: ProviderData | null;
  error: DemoError | null;
  replayed: boolean;
  payment_mode: string;
}

export interface Dashboard {
  agent: AgentDashboard;
  platform: PlatformDashboard;
  providers: ProviderDashboard[];
  transactions: Transaction[];
  payment_mode: string;
  currency: string;
  chain_id: number;
}

export interface DiscoveryEndpoint {
  endpoint_id: string;
  provider: string;
  description: string;
  price_cents: number;
  provider_price_cents: number;
  platform_fee_cents: number;
  input_schema: Record<string, unknown>;
  currency: string;
  payment_protocol: string;
  payment_method: string;
  chain_id: number;
  token_address: string;
  execute_path: string;
  pay_to: string;
  provider_wallet: string;
  affordable: boolean;
  relevance: number;
}

export interface ProviderService extends ProviderDashboard {
  description: string;
  endpoint_path: string;
  price_cents: number;
  provider_amount_cents: number;
  platform_fee_cents: number;
}

export interface ProviderTransaction extends Omit<Transaction, "data"> {
  created_at: number;
  paid_at: number | null;
}

export interface ProviderOverview {
  agent: AgentDashboard;
  providers: ProviderService[];
  transactions: ProviderTransaction[];
  currency: string;
  chain_id: number;
  payment_mode: string;
}

export interface Discovery {
  session_id: string;
  query: string;
  endpoints: DiscoveryEndpoint[];
  total_price_cents: number;
  remaining_cents: number;
  payment_mode: string;
  discovery_is_free: boolean;
}

export interface GatewayEvent {
  id: number;
  session_id: string;
  execution_id: string | null;
  type: string;
  detail: Record<string, unknown>;
  created: number;
}

export interface RunnerJob {
  status: JobStatus;
  mode: "all" | "next" | null;
  current_endpoint: string | null;
  last_error: DemoError | null;
}

export interface RunnerState {
  dashboard: Dashboard;
  events: GatewayEvent[];
  next_cursor: number;
  discovery: Discovery | null;
  job: RunnerJob;
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
  after: number,
  includeChain: boolean,
  signal?: AbortSignal,
): Promise<RunnerState> {
  const query = new URLSearchParams({
    after: String(after),
    chain: includeChain ? "1" : "0",
  });
  return request<RunnerState>(`/state?${query}`, { signal });
}

export function fetchProviderOverview(includeChain: boolean, signal?: AbortSignal): Promise<ProviderOverview> {
  return request<ProviderOverview>(`/providers?chain=${includeChain ? "1" : "0"}`, { signal });
}

export function discoverServices(): Promise<Discovery> {
  return mutate<Discovery>("/discover");
}

export function startRun(mode: "all" | "next"): Promise<{ job: RunnerJob }> {
  return mutate<{ job: RunnerJob }>("/run", { mode });
}

export function pauseRun(): Promise<{ job: RunnerJob }> {
  return mutate<{ job: RunnerJob }>("/pause");
}

export function resetDemo(): Promise<AgentDashboard> {
  return mutate<AgentDashboard>("/reset");
}
