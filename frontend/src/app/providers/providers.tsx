"use client";
import { Icon, type IconName } from "@/components/icons";
import { EarningsChart } from "@/components/earnings-chart";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableCaption,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Alert } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/select-field";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from "@/components/ui/pagination";
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Empty as EmptyState } from "@/components/ui/empty";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { money, shortAddress, shortReference } from "@/lib/demo";
import { NumberTicker } from "@/components/ui/number-ticker";
import { WalletTicker } from "@/components/ui/wallet-ticker";
import type {
  ProviderService,
  ProviderTransaction,
  PublicReceipt,
} from "@/lib/openmcp";
import {
  isReceived,
  paymentLabel,
  paymentsCsv,
  paymentTime,
  scopedTransactions,
  type PaymentFilter,
  type Period,
  type ProviderView,
} from "@/lib/providers";
import { useProviderData } from "./use-provider-data";

function Brand() {
  return (
    <Link href="/" className="provider-brand" aria-label="OpenMCP home">
      <svg
        width="25"
        height="27"
        viewBox="0 0 25 27"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M3 24V11a9.5 9.5 0 0 1 19 0v13M9 24v-9a3.5 3.5 0 0 1 7 0v9"
          stroke="currentColor"
          strokeWidth="1.7"
        />
      </svg>
      <span>OpenMCP</span>
    </Link>
  );
}

function ProviderMark({
  name,
  small = false,
}: {
  name: string;
  small?: boolean;
}) {
  return (
    <Avatar
      className={`provider-mark ${small ? "small" : ""}`}
      aria-hidden="true"
    >
      <AvatarFallback>{name.slice(0, 1)}</AvatarFallback>
    </Avatar>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [status, setStatus] = useState("Copy");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setStatus("Copied");
    } catch {
      setStatus("Copy failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("Copy"), 2200);
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          type="button"
          className="provider-icon-button"
          onClick={copy}
          aria-label={`${status} ${label}`}
        >
          <Icon name={status === "Copied" ? "check" : "copy"} size={15} />
          <span className="provider-sr-only" role="status">
            {status !== "Copy" ? status : ""}
          </span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {status} {label}
      </TooltipContent>
    </Tooltip>
  );
}

function ReceiptLink({
  receipt,
  label,
}: {
  receipt: PublicReceipt | null;
  label: string;
}) {
  if (!receipt?.reference || !receipt.explorer_url)
    return <span className="muted">Awaiting confirmation</span>;
  return (
    <a
      className="provider-receipt"
      href={receipt.explorer_url}
      target="_blank"
      rel="noreferrer"
      aria-label={`View ${label} on the explorer`}
    >
      <span>{shortReference(receipt.reference)}</span>
      <Icon name="external" size={13} />
    </a>
  );
}

function PaymentDetail({
  transaction,
  onClose,
}: {
  transaction: ProviderTransaction | null;
  onClose: () => void;
}) {
  const received = transaction ? isReceived(transaction) : false;
  return (
    <Dialog
      open={Boolean(transaction)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="provider-dialog" showCloseButton={false}>
        {transaction && (
          <>
            <div className="provider-dialog-heading">
              <div>
                <p className="eyebrow">Payment details</p>
                <DialogTitle>{transaction.provider}</DialogTitle>
                <DialogDescription className="sr-only">
                  Payment amounts, settlement status, and receipts.
                </DialogDescription>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                type="button"
                className="provider-icon-button"
                onClick={onClose}
                aria-label="Close payment details"
              >
                <Icon name="close" />
              </Button>
            </div>
            <div className="provider-detail-amount">
              <span>
                {received ? "+" : ""}
                {money(transaction.provider_amount_cents)}
              </span>
              <span>USD · {received ? "received" : "expected"}</span>
              <Badge
                className={`provider-status ${received ? "received" : "pending"}`}
              >
                {paymentLabel(transaction)}
              </Badge>
            </div>
            <dl className="provider-detail-list">
              <div>
                <dt>Agent payment</dt>
                <dd>{money(transaction.price_cents)}</dd>
              </div>
              <div>
                <dt>OpenMCP fee</dt>
                <dd>−{money(transaction.platform_fee_cents)}</dd>
              </div>
              <div className="provider-detail-net">
                <dt>
                  Provider {received ? "received" : "receives on settlement"}
                </dt>
                <dd>{money(transaction.provider_amount_cents)}</dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd className="mono">/{transaction.endpoint_id}</dd>
              </div>
              <div>
                <dt>Data delivery</dt>
                <dd>
                  {transaction.status === "completed" ? "Delivered" : "Pending"}
                </dd>
              </div>
              <div>
                <dt>{received ? "Payment date" : "Request date"}</dt>
                <dd>
                  {new Date(paymentTime(transaction) * 1000).toLocaleString(
                    "en-US",
                    { dateStyle: "medium", timeStyle: "short" },
                  )}
                </dd>
              </div>
            </dl>
            <div className="provider-receipt-block">
              <p>Payment trail</p>
              <div>
                <span>Agent → OpenMCP</span>
                <ReceiptLink
                  receipt={transaction.agent_to_openmcp}
                  label="agent payment"
                />
              </div>
              <div>
                <span>OpenMCP → provider</span>
                <ReceiptLink
                  receipt={transaction.openmcp_to_provider}
                  label="provider payment"
                />
              </div>
            </div>
            {transaction.error && (
              <p className="provider-detail-error">
                {transaction.error.message}
              </p>
            )}
            <div className="provider-detail-id">
              <span className="mono">{transaction.execution_id}</span>
              <CopyButton value={transaction.execution_id} label="request ID" />
            </div>
            <p className="provider-fine-print">
              Tempo Moderato testnet. These tokens have no monetary value.
            </p>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

const navigation: { id: ProviderView; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "payments", label: "Payments", icon: "payments" },
  { id: "services", label: "Services", icon: "services" },
  { id: "wallets", label: "Wallets", icon: "wallets" },
];

const headings: Record<ProviderView, { title: string; description: string }> = {
  overview: {
    title: "Your data, earning.",
    description: "A clear view of the value your services create.",
  },
  payments: {
    title: "Every payment, accounted for.",
    description: "Follow each request from agent payment to provider receipt.",
  },
  services: {
    title: "Useful data. Open for business.",
    description: "Your registered services, prices, and earnings in one place.",
  },
  wallets: {
    title: "Straight to your wallet.",
    description:
      "Confirmed balances and the addresses that receive your payments.",
  },
};

export default function Providers() {
  const { data, error, updatedAt, refreshing, refresh } = useProviderData();
  const [view, setView] = useState<ProviderView>("overview");
  const [provider, setProvider] = useState("all");
  const [period, setPeriod] = useState<Period>("7");
  const [filter, setFilter] = useState<PaymentFilter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const seenReceipts = useRef<Set<string> | null>(null);

  useEffect(() => {
    const readHash = () => {
      const hash = window.location.hash.slice(1);
      const match = navigation.find((item) => item.id === hash);
      if (match) setView(match.id);
    };
    readHash();
    window.addEventListener("hashchange", readHash);
    return () => window.removeEventListener("hashchange", readHash);
  }, []);

  useEffect(() => {
    if (!data) return;
    const received = data.transactions.filter(isReceived);
    const latest = received.filter(
      (transaction) => !seenReceipts.current?.has(transaction.execution_id),
    );
    if (seenReceipts.current && latest.length) {
      toast.success(
        `${latest.length === 1 ? `${latest[0].provider} received` : `${latest.length} new payments received ·`} +${money(latest.reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0))} USD`,
      );
    }
    seenReceipts.current = new Set(
      received.map((transaction) => transaction.execution_id),
    );
  }, [data]);

  const now = updatedAt ?? 0;
  const providers =
    data?.providers.filter(
      (item) => provider === "all" || item.endpoint_id === provider,
    ) ?? [];
  const transactions = scopedTransactions(data, provider, period, now);
  const received = transactions.filter(isReceived);
  const pending = transactions.filter(
    (transaction) =>
      !isReceived(transaction) && transaction.status !== "quoted",
  );
  const net = received.reduce(
    (sum, transaction) => sum + transaction.provider_amount_cents,
    0,
  );
  const fees = received.reduce(
    (sum, transaction) => sum + transaction.platform_fee_cents,
    0,
  );
  const pendingAmount = pending.reduce(
    (sum, transaction) => sum + transaction.provider_amount_cents,
    0,
  );
  const gross = received.reduce(
    (sum, transaction) => sum + transaction.price_cents,
    0,
  );
  const allEarnings = (data?.transactions ?? [])
    .filter(
      (transaction) =>
        isReceived(transaction) &&
        (provider === "all" || transaction.endpoint_id === provider),
    )
    .reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
  const sessionEarnings = providers.reduce(
    (sum, item) => sum + item.session_earned_cents,
    0,
  );
  const filtered = transactions.filter((transaction) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "received"
        ? isReceived(transaction)
        : !isReceived(transaction));
    return (
      matchesFilter &&
      `${transaction.provider} ${transaction.endpoint_id} ${transaction.execution_id} ${transaction.openmcp_to_provider?.reference ?? ""}`
        .toLowerCase()
        .includes(search.toLowerCase())
    );
  });
  const pageCount = Math.max(1, Math.ceil(filtered.length / 8));
  const currentPage = Math.min(page, pageCount - 1);
  const selected =
    data?.transactions.find(
      (transaction) => transaction.execution_id === selectedId,
    ) ?? null;
  const providerName =
    data?.providers.find((item) => item.endpoint_id === provider)?.name ??
    "All providers";
  const periodLabel = period === "all" ? "All time" : `Last ${period} days`;

  function exportPayments() {
    const blob = new Blob(["\uFEFF", paymentsCsv(filtered)], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `openmcp-payments-${provider}-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function paymentTable(compact = false) {
    const rows = compact
      ? transactions.slice(0, 5)
      : filtered.slice(currentPage * 8, currentPage * 8 + 8);
    return (
      <>
        <div className="provider-table-scroll">
          <Table className="provider-table">
            <TableCaption className="provider-sr-only">
              {compact ? "Recent payments" : "Provider payments"} in USD
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Service / provider</TableHead>
                <TableHead scope="col">Status</TableHead>
                <TableHead scope="col">
                  {compact ? "Date" : "Agent paid"}
                </TableHead>
                <TableHead scope="col" className="provider-align-right">
                  {compact ? "Net amount" : "Fee"}
                </TableHead>
                {!compact && (
                  <TableHead scope="col" className="provider-align-right">
                    Net amount
                  </TableHead>
                )}
                <TableHead scope="col">
                  <span className="provider-sr-only">Details</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((transaction) => (
                <TableRow
                  key={transaction.execution_id}
                  className={
                    isReceived(transaction) ? "" : "provider-pending-row"
                  }
                >
                  <TableCell>
                    <div className="provider-table-identity">
                      <ProviderMark name={transaction.provider} small />
                      <div>
                        <span>{transaction.provider}</span>
                        <code>/{transaction.endpoint_id}</code>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge
                      className={`provider-status ${isReceived(transaction) ? "received" : "pending"}`}
                    >
                      {isReceived(transaction) && (
                        <Icon name="check" size={12} />
                      )}
                      {paymentLabel(transaction)}
                    </Badge>
                  </TableCell>
                  <TableCell className={compact ? "muted" : "provider-numeric"}>
                    {compact
                      ? new Date(
                          paymentTime(transaction) * 1000,
                        ).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })
                      : money(transaction.price_cents)}
                  </TableCell>
                  <TableCell
                    className={`provider-align-right provider-numeric ${compact && isReceived(transaction) ? "provider-positive" : "muted"}`}
                  >
                    {compact
                      ? `${isReceived(transaction) ? "+" : ""}${money(transaction.provider_amount_cents)}`
                      : money(transaction.platform_fee_cents)}
                  </TableCell>
                  {!compact && (
                    <TableCell
                      className={`provider-align-right provider-numeric ${isReceived(transaction) ? "provider-positive" : "muted"}`}
                    >
                      {isReceived(transaction) ? "+" : ""}
                      {money(transaction.provider_amount_cents)}
                    </TableCell>
                  )}
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      type="button"
                      className="provider-icon-button"
                      onClick={() => setSelectedId(transaction.execution_id)}
                      aria-label={`View payment from ${transaction.provider}, ${money(transaction.provider_amount_cents)} USD`}
                    >
                      <Icon name="arrow" size={16} />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {rows.length === 0 && (
          <EmptyState className="provider-empty">
            <div className="provider-empty-icon">
              <Icon name="payments" size={23} />
            </div>
            <h3>
              {!data
                ? "Waiting for the connection"
                : search || filter !== "all"
                  ? "No matching payments"
                  : "Ready for your first payment"}
            </h3>
            <p>
              {!data
                ? "Your payment history will appear when the local stack connects."
                : search || filter !== "all"
                  ? "Try another search or payment status."
                  : "When an agent pays for your service, you’ll see it here."}
            </p>
            {data && !search && filter === "all" && (
              <Link href="/demo" className="provider-inline-link">
                Open the FreightFlow demo <Icon name="arrow" size={15} />
              </Link>
            )}
          </EmptyState>
        )}
        {!compact && (
          <div className="provider-pagination">
            <span>
              {filtered.length
                ? `${currentPage * 8 + 1}–${Math.min((currentPage + 1) * 8, filtered.length)} of ${filtered.length} payments`
                : "0 payments"}
            </span>
            <Pagination className="w-auto mx-0" aria-label="Payment pages">
              <PaginationContent className="m-0 p-0 list-none">
                <PaginationItem>
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    disabled={currentPage === 0}
                    onClick={() => setPage(currentPage - 1)}
                  >
                    Previous
                  </Button>
                </PaginationItem>
                <PaginationItem>
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    disabled={currentPage + 1 >= pageCount}
                    onClick={() => setPage(currentPage + 1)}
                  >
                    Next
                  </Button>
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          </div>
        )}
      </>
    );
  }

  function walletCard(service: ProviderService) {
    const balance = service.wallet_balance;
    const total = (data?.transactions ?? [])
      .filter(
        (transaction) =>
          transaction.endpoint_id === service.endpoint_id &&
          isReceived(transaction),
      )
      .reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
    return (
      <Card
        as="article"
        className="provider-wallet-card"
        key={service.endpoint_id}
      >
        <div className="provider-section-heading">
          <div className="provider-service-heading">
            <ProviderMark name={service.name} />
            <h2>{service.name}</h2>
          </div>
          <Icon name="wallets" />
        </div>
        <p className="provider-card-label">On-chain balance</p>
        <div className="provider-wallet-amount">
          <WalletTicker balance={balance} />
        </div>
        <div className="provider-address">
          <code title={service.address}>{service.address}</code>
          <CopyButton
            value={service.address}
            label={`${service.name} wallet address`}
          />
        </div>
        <dl className="provider-wallet-summary">
          <div>
            <dt>All-time ledger earnings</dt>
            <dd>
              <NumberTicker value={total / 100} decimalPlaces={2} />{" "}
              <span>USD</span>
            </dd>
          </div>
          <div>
            <dt>Current session earnings</dt>
            <dd>
              <NumberTicker
                value={service.session_earned_cents / 100}
                decimalPlaces={2}
              />{" "}
              <span>USD</span>
            </dd>
          </div>
          <div>
            <dt>Network</dt>
            <dd>Tempo Moderato</dd>
          </div>
        </dl>
        {balance?.error && (
          <p className="provider-detail-error">
            Balance unavailable. The network read will retry automatically.
          </p>
        )}
        <a
          className="provider-inline-link"
          href={`https://explore.moderato.tempo.xyz/address/${service.address}`}
          target="_blank"
          rel="noreferrer"
        >
          View wallet on explorer <Icon name="external" size={14} />
        </a>
      </Card>
    );
  }

  return (
    <div className="provider-app">
      <a href="#provider-main" className="skip-link">
        Skip to content
      </a>
      <aside className="provider-sidebar">
        <Brand />
        <div className="provider-workspace">
          <span className="provider-workspace-icon">
            <Icon name="services" />
          </span>
          <div>
            <span>Provider workspace</span>
            <small>OpenMCP network</small>
          </div>
        </div>
        <p className="provider-nav-label">WORKSPACE</p>
        <nav aria-label="Provider dashboard">
          {navigation.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className={view === item.id ? "active" : ""}
              aria-current={view === item.id ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.id === "services" && data && (
                <small>{data.providers.length}</small>
              )}
            </a>
          ))}
        </nav>
        <div className="provider-sidebar-bottom">
          <div className="provider-brand-card">
            <Image
              src="/images/lavender-temple.jpeg"
              alt=""
              width={360}
              height={170}
              unoptimized
            />
            <div>
              <p>Built for useful data.</p>
              <span>Paid for every exchange.</span>
              <Link href="/demo">
                See it in motion <Icon name="arrow" size={14} />
              </Link>
            </div>
          </div>
          <Link href="/" className="provider-back">
            ← Back to OpenMCP
          </Link>
          <div className="provider-environment">
            <span />
            Test environment<small>Valueless tokens</small>
          </div>
        </div>
      </aside>

      <div className="provider-workspace-main">
        <header className="provider-topbar">
          <Breadcrumb>
            <BreadcrumbList className="m-0 p-0 list-none text-xs">
              <BreadcrumbItem>Workspace</BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>
                  {navigation.find((item) => item.id === view)?.label}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          <div className="provider-topbar-actions">
            <span
              className={`provider-live ${error ? "offline" : !data ? "connecting" : ""}`}
            >
              <i />
              {error ? "Connection interrupted" : data ? "Live" : "Connecting"}
            </span>
            <Link href="/demo">
              Agent demo <Icon name="external" size={13} />
            </Link>
            <Avatar
              className="provider-avatar"
              title="Local provider workspace"
            >
              <AvatarFallback>O</AvatarFallback>
            </Avatar>
          </div>
        </header>
        <div className="provider-money-strip">
          <span>
            Provider earnings{" "}
            <strong>
              {data ? (
                <NumberTicker value={allEarnings / 100} decimalPlaces={2} />
              ) : (
                "—"
              )}
            </strong>
            <small>USD · all time</small>
          </span>
          <span>
            Agent budget left{" "}
            <strong>
              {data ? (
                <NumberTicker
                  value={data.agent.remaining_cents / 100}
                  decimalPlaces={2}
                />
              ) : (
                "—"
              )}
            </strong>
            <small>USD · current session</small>
          </span>
        </div>

        <main id="provider-main" className="provider-main">
          <div className="provider-page-heading">
            <div>
              <p className="eyebrow">PROVIDER {view.toUpperCase()}</p>
              <h1>{headings[view].title}</h1>
              <p>{headings[view].description}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              type="button"
              className="provider-secondary-button"
              onClick={exportPayments}
              disabled={!data || filtered.length === 0}
            >
              <Icon name="download" size={16} />
              Export payments
            </Button>
          </div>
          <div className="provider-toolbar">
            <div className="provider-filters">
              <SelectField
                value={provider}
                label="Provider"
                onValueChange={(value) => {
                  setProvider(value);
                  setPage(0);
                }}
                options={[
                  { value: "all", label: "All providers" },
                  ...(data?.providers.map((item) => ({
                    value: item.endpoint_id,
                    label: item.name,
                  })) ?? []),
                ]}
              />
              <SelectField
                value={period}
                label="Reporting period"
                onValueChange={(value) => {
                  setPeriod(value as Period);
                  setPage(0);
                }}
                options={[
                  { value: "7", label: "Last 7 days" },
                  { value: "30", label: "Last 30 days" },
                  { value: "all", label: "All time" },
                ]}
              />
            </div>
            <div className="provider-update">
              <span>
                {updatedAt
                  ? `Updated ${new Date(updatedAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`
                  : "Connecting to OpenMCP"}
              </span>
              <Button
                variant="ghost"
                size="icon-sm"
                type="button"
                className="provider-icon-button"
                onClick={refresh}
                disabled={refreshing}
                aria-label="Refresh provider data"
              >
                <Icon name="refresh" size={15} />
              </Button>
            </div>
          </div>
          {error && (
            <Alert className="provider-connection-error" role="alert">
              <Icon name="refresh" />
              <div>
                <strong>
                  {data
                    ? "Connection interrupted — showing last received data"
                    : "Your local stack is offline"}
                </strong>
                <p>{error}</p>
              </div>
              <Button
                variant="default"
                type="button"
                onClick={refresh}
                disabled={refreshing}
              >
                Retry
              </Button>
            </Alert>
          )}

          {(view === "overview" || view === "payments") && (
            <Card className="provider-metrics">
              <section className="provider-metric primary">
                <div className="provider-metric-label">
                  <span>Net earnings</span>
                  <Icon name="payments" size={17} />
                </div>
                <div className="provider-metric-value">
                  {data ? (
                    <NumberTicker value={net / 100} decimalPlaces={2} />
                  ) : (
                    "—"
                  )}
                  <span>USD</span>
                </div>
                <p>
                  <span className="provider-dot" />
                  {periodLabel} · after platform fees
                </p>
              </section>
              <section className="provider-metric">
                <div className="provider-metric-label">
                  <span>Payments received</span>
                  <Icon name="check" size={17} />
                </div>
                <div className="provider-metric-value">
                  {data ? <NumberTicker value={received.length} /> : "—"}
                  <span>payments</span>
                </div>
                <p>
                  {data
                    ? `${money(gross)} USD in agent purchases`
                    : "Waiting for payment records"}
                </p>
              </section>
              <section className="provider-metric">
                <div className="provider-metric-label">
                  <span>Pending earnings</span>
                  <Icon name="wallets" size={17} />
                </div>
                <div className="provider-metric-value">
                  {data ? (
                    <NumberTicker
                      value={pendingAmount / 100}
                      decimalPlaces={2}
                    />
                  ) : (
                    "—"
                  )}
                  <span>USD</span>
                </div>
                <p>
                  {pending.length
                    ? `${pending.length} ${pending.length === 1 ? "payment awaiting" : "payments awaiting"} confirmation`
                    : data
                      ? "You’re all caught up"
                      : "Waiting for payment records"}
                </p>
              </section>
            </Card>
          )}

          {view === "overview" && (
            <>
              <div className="provider-overview-grid">
                <Card as="section" className="provider-panel provider-earnings">
                  <div className="provider-section-heading">
                    <div>
                      <h2>Earnings over time</h2>
                      <p>
                        {periodLabel} · {providerName}
                      </p>
                    </div>
                    <span className="provider-unit-label">Net earnings</span>
                  </div>
                  <EarningsChart
                    transactions={transactions}
                    period={period}
                    now={now}
                    loaded={Boolean(data)}
                  />
                </Card>
                <Card
                  as="section"
                  className="provider-panel provider-breakdown"
                >
                  <div className="provider-section-heading">
                    <h2>The payment split</h2>
                    <Icon name="payments" />
                  </div>
                  <p>Useful data. A simple exchange.</p>
                  <div className="provider-split-amount">
                    {data ? (
                      <NumberTicker value={gross / 100} decimalPlaces={2} />
                    ) : (
                      "—"
                    )}
                    <span>USD paid by agents</span>
                  </div>
                  <Progress
                    className="provider-split-bar"
                    aria-label={`${money(net)} provider earnings and ${money(fees)} platform fees`}
                    value={gross ? (net / gross) * 100 : 0}
                  />
                  <dl>
                    <div>
                      <dt>
                        <i />
                        Provider earnings
                      </dt>
                      <dd>
                        {data ? (
                          <NumberTicker value={net / 100} decimalPlaces={2} />
                        ) : (
                          "—"
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>
                        <i />
                        OpenMCP fees
                      </dt>
                      <dd>
                        {data ? (
                          <NumberTicker value={fees / 100} decimalPlaces={2} />
                        ) : (
                          "—"
                        )}
                      </dd>
                    </div>
                  </dl>
                  <div className="provider-settlement-note">
                    <Icon name="wallets" size={17} />
                    <span>
                      Payments settle directly to your provider wallet.
                    </span>
                  </div>
                </Card>
              </div>
              <Card
                as="section"
                className="provider-panel provider-payment-panel"
              >
                <div className="provider-section-heading">
                  <div>
                    <h2>Recent payments</h2>
                    <p>Each receipt is a little more value unlocked.</p>
                  </div>
                  <a href="#payments" className="provider-inline-link">
                    View all payments <Icon name="arrow" size={15} />
                  </a>
                </div>
                {paymentTable(true)}
              </Card>
              <section className="provider-service-strip">
                <div>
                  <h2>Your services</h2>
                  <p>
                    {data
                      ? `${providers.length} registered ${providers.length === 1 ? "endpoint" : "endpoints"}`
                      : "Connecting"}
                  </p>
                </div>
                <div>
                  {providers.map((service) => (
                    <a
                      href="#services"
                      key={service.endpoint_id}
                      onClick={() => setProvider(service.endpoint_id)}
                    >
                      <ProviderMark name={service.name} small />
                      <span>
                        {service.name}
                        <small>
                          {money(service.provider_amount_cents)} per call
                        </small>
                      </span>
                      <Icon name="arrow" size={14} />
                    </a>
                  ))}
                </div>
              </section>
            </>
          )}

          {view === "payments" && (
            <Card
              as="section"
              className="provider-panel provider-payment-panel"
            >
              <div className="provider-section-heading">
                <div>
                  <h2>Payment history</h2>
                  <p>
                    Amounts in USD. Pending amounts are expected, not settled.
                  </p>
                </div>
              </div>
              <div className="provider-payment-filters">
                <ToggleGroup
                  type="single"
                  value={filter}
                  onValueChange={(value) => {
                    if (value) {
                      setFilter(value as PaymentFilter);
                      setPage(0);
                    }
                  }}
                  className="provider-filter-tabs"
                  aria-label="Payment status"
                >
                  {(["all", "received", "pending"] as PaymentFilter[]).map(
                    (value) => (
                      <ToggleGroupItem
                        key={value}
                        value={value}
                        className={filter === value ? "active" : ""}
                      >
                        {value === "all"
                          ? "All payments"
                          : value === "received"
                            ? "Received"
                            : "Pending"}
                      </ToggleGroupItem>
                    ),
                  )}
                </ToggleGroup>
                <Label className="provider-search">
                  <Icon name="search" size={16} />
                  <Input
                    variant="bare"
                    aria-label="Search payments"
                    placeholder="Search payments…"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(0);
                    }}
                  />
                </Label>
              </div>
              {paymentTable()}
            </Card>
          )}

          {view === "services" && (
            <div className="provider-service-grid">
              {providers.map((service) => {
                const servicePayments = received.filter(
                  (transaction) =>
                    transaction.endpoint_id === service.endpoint_id,
                );
                const earnings = servicePayments.reduce(
                  (sum, transaction) => sum + transaction.provider_amount_cents,
                  0,
                );
                return (
                  <Card
                    as="article"
                    className="provider-service-card"
                    key={service.endpoint_id}
                  >
                    <div className="provider-section-heading">
                      <ProviderMark name={service.name} />
                      <Badge className="provider-status received">
                        Registered
                      </Badge>
                    </div>
                    <h2>{service.name}</h2>
                    <p>{service.description}</p>
                    <div className="provider-endpoint">
                      <span>POST</span>
                      <code>{service.endpoint_path}</code>
                      <CopyButton
                        value={service.endpoint_path}
                        label="endpoint path"
                      />
                    </div>
                    <div className="provider-service-pricing">
                      <div>
                        <span>Agent pays</span>
                        <strong>{money(service.price_cents)}</strong>
                      </div>
                      <div>
                        <span>You receive</span>
                        <strong>{money(service.provider_amount_cents)}</strong>
                      </div>
                      <div>
                        <span>Platform fee</span>
                        <strong>{money(service.platform_fee_cents)}</strong>
                      </div>
                    </div>
                    <p className="provider-fine-print">USD per request</p>
                    <div className="provider-service-performance">
                      <span>
                        {periodLabel}
                        <strong>
                          <NumberTicker value={servicePayments.length} />{" "}
                          payments
                        </strong>
                      </span>
                      <span>
                        Net earnings
                        <strong>
                          <NumberTicker
                            value={earnings / 100}
                            decimalPlaces={2}
                          />{" "}
                          <small>USD</small>
                        </strong>
                      </span>
                    </div>
                    <a
                      className="provider-inline-link"
                      href="#payments"
                      onClick={() => {
                        setProvider(service.endpoint_id);
                        setSearch("");
                        setFilter("all");
                        setPage(0);
                      }}
                    >
                      View payments <Icon name="arrow" size={15} />
                    </a>
                  </Card>
                );
              })}
              {!data && (
                <EmptyState className="provider-empty">
                  <h2>Connecting to your services</h2>
                  <p>
                    Registered endpoints will appear when the local stack is
                    available.
                  </p>
                </EmptyState>
              )}
            </div>
          )}

          {view === "wallets" && (
            <>
              <Alert role="status" className="provider-wallet-notice">
                <Icon name="wallets" />
                <p>
                  Wallet balances include earlier payments and testnet funding.
                  Ledger earnings track payments recorded by this OpenMCP
                  instance. Network fees can make these amounts differ.
                </p>
              </Alert>
              <div className="provider-wallet-grid">
                {providers.map(walletCard)}
                {!data && (
                  <EmptyState className="provider-empty">
                    <h2>Connecting to your wallets</h2>
                    <p>Balances are read directly from Tempo testnet.</p>
                  </EmptyState>
                )}
              </div>
              <div className="provider-agent-card">
                <div>
                  <p className="eyebrow">CURRENT AGENT SESSION</p>
                  <h2>
                    {data ? (
                      <NumberTicker
                        value={data.agent.remaining_cents / 100}
                        decimalPlaces={2}
                      />
                    ) : (
                      "—"
                    )}{" "}
                    <span>USD remaining</span>
                  </h2>
                  <p>
                    Of {data ? money(data.agent.budget_cents) : "—"} service
                    budget ·{" "}
                    <NumberTicker
                      value={sessionEarnings / 100}
                      decimalPlaces={2}
                    />{" "}
                    earned by {providerName.toLowerCase()} this session
                  </p>
                </div>
                <div>
                  <span className="mono">
                    {shortAddress(data?.agent.address)}
                  </span>
                  <span>
                    Wallet balance:{" "}
                    <WalletTicker balance={data?.agent.wallet_balance} />
                  </span>
                </div>
              </div>
            </>
          )}

          <footer className="provider-footer">
            <span>
              <i />
              Tempo testnet · valueless test tokens
            </span>
            <span>
              Payments powered by OpenMCP{" "}
              <span className="provider-footer-symbol">↗</span>
            </span>
          </footer>
        </main>
      </div>
      <PaymentDetail
        transaction={selected}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
