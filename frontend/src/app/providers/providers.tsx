"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { money, shortAddress, shortReference } from "@/lib/demo";
import { NumberTicker } from "@/components/ui/number-ticker";
import { WalletTicker } from "@/components/ui/wallet-ticker";
import type { ProviderService, ProviderTransaction, PublicReceipt } from "@/lib/openmcp";
import {
  earningsSeries, isReceived, paymentLabel, paymentsCsv, paymentTime, scopedTransactions,
  type PaymentFilter, type Period, type ProviderView,
} from "@/lib/providers";
import { useProviderData } from "./use-provider-data";

type IconName = "overview" | "payments" | "services" | "wallets" | "arrow" | "download" | "refresh" | "search" | "external" | "check" | "copy" | "close";
function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    payments: <><path d="M4 8h15m-4-4 4 4-4 4M20 16H5m4-4-4 4 4 4" /></>,
    services: <><path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 20" /></>,
    wallets: <><path d="M20 8V5H5a2 2 0 0 0 0 4h15v11H5a2 2 0 0 1-2-2V7" /><path d="M20 12h-5v5h5m-3-2.5h.1" /></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" /></>,
    refresh: <><path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5m-4 6a8 8 0 0 0 14 5l3-3m0 5v-5h-5" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    external: <><path d="M14 3h7v7m0-7L10 14m0-10H4v16h16v-6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V3H3v13h5" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Brand() {
  return <Link href="/" className="provider-brand" aria-label="OpenMCP home"><svg width="25" height="27" viewBox="0 0 25 27" fill="none" aria-hidden="true"><path d="M3 24V11a9.5 9.5 0 0 1 19 0v13M9 24v-9a3.5 3.5 0 0 1 7 0v9" stroke="currentColor" strokeWidth="1.7" /></svg><span>OpenMCP</span></Link>;
}

function ProviderMark({ name, small = false }: { name: string; small?: boolean }) {
  return <span className={`provider-mark ${small ? "small" : ""}`} aria-hidden="true">{name.slice(0, 1)}</span>;
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [status, setStatus] = useState("Copy");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  async function copy() {
    try { await navigator.clipboard.writeText(value); setStatus("Copied"); }
    catch { setStatus("Copy failed"); }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus("Copy"), 2200);
  }
  return <button type="button" className="provider-icon-button" onClick={copy} aria-label={`${status} ${label}`} title={`${status} ${label}`}><Icon name={status === "Copied" ? "check" : "copy"} size={15} /><span className="provider-sr-only" role="status">{status !== "Copy" ? status : ""}</span></button>;
}

function ReceiptLink({ receipt, label }: { receipt: PublicReceipt | null; label: string }) {
  if (!receipt?.reference || !receipt.explorer_url) return <span className="muted">Awaiting confirmation</span>;
  return <a className="provider-receipt" href={receipt.explorer_url} target="_blank" rel="noreferrer" aria-label={`View ${label} on the explorer`}><span>{shortReference(receipt.reference)}</span><Icon name="external" size={13} /></a>;
}

function EarningsChart({ transactions, period, now, loaded }: { transactions: ProviderTransaction[]; period: Period; now: number; loaded: boolean }) {
  const series = loaded ? earningsSeries(transactions, period, now) : [];
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(100, Math.ceil(Math.max(...series.map(point => point.cents), 1) / 100) * 100);
  const activePoint = active === null ? null : series[active];
  const hasPayments = transactions.some(isReceived);
  return <div className="provider-chart">
    <div className="provider-chart-caption"><span><i />Net provider earnings</span><span aria-live="polite">{activePoint ? `${activePoint.label} · ${money(activePoint.cents)} test pathUSD` : "test pathUSD"}</span></div>
    <div className="provider-chart-body">
      <div className="provider-chart-axis">{[1, 2 / 3, 1 / 3, 0].map(fraction => <span key={fraction}>{money(Math.round(max * fraction))}</span>)}</div>
      <div className="provider-plot">
        <div className="provider-gridlines" aria-hidden="true"><i /><i /><i /><i /></div>
        <div className="provider-bars" onMouseLeave={() => setActive(null)}>
          {series.map((point, index) => <button key={point.start} type="button" className={active === index ? "is-active" : ""} aria-label={`${point.label}: ${money(point.cents)} test pathUSD received`} onMouseEnter={() => setActive(index)} onFocus={() => setActive(index)} onBlur={() => setActive(null)}><span style={{ height: `${point.cents / max * 100}%` }} /></button>)}
        </div>
        {!hasPayments && <div className="provider-chart-empty"><span>{loaded ? "Your next payment starts here" : "Connecting to your earnings"}</span><p>{loaded ? "Confirmed payments will appear automatically." : "Reading your provider ledger…"}</p></div>}
      </div>
    </div>
    <div className="provider-chart-dates"><span>{series[0]?.label}</span><span>{series[Math.floor(series.length / 2)]?.label}</span><span>{series.at(-1)?.label}</span></div>
  </div>;
}

function PaymentDetail({ transaction, onClose }: { transaction: ProviderTransaction | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (transaction) ref.current?.showModal();
    else ref.current?.close();
  }, [transaction]);
  const received = transaction ? isReceived(transaction) : false;
  return <dialog ref={ref} className="provider-dialog" onCancel={onClose} onClose={onClose} aria-labelledby="payment-title" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    {transaction && <>
      <div className="provider-dialog-heading"><div><p className="eyebrow">Payment details</p><h2 id="payment-title">{transaction.provider}</h2></div><button type="button" className="provider-icon-button" onClick={onClose} aria-label="Close payment details"><Icon name="close" /></button></div>
      <div className="provider-detail-amount"><span>{received ? "+" : ""}{money(transaction.provider_amount_cents)}</span><span>test pathUSD · {received ? "received" : "expected"}</span><span className={`provider-status ${received ? "received" : "pending"}`}>{paymentLabel(transaction)}</span></div>
      <dl className="provider-detail-list">
        <div><dt>Agent payment</dt><dd>{money(transaction.price_cents)}</dd></div>
        <div><dt>OpenMCP fee</dt><dd>−{money(transaction.platform_fee_cents)}</dd></div>
        <div className="provider-detail-net"><dt>Provider {received ? "received" : "receives on settlement"}</dt><dd>{money(transaction.provider_amount_cents)}</dd></div>
        <div><dt>Service</dt><dd className="mono">/{transaction.endpoint_id}</dd></div>
        <div><dt>Data delivery</dt><dd>{transaction.status === "completed" ? "Delivered" : "Pending"}</dd></div>
        <div><dt>{received ? "Payment date" : "Request date"}</dt><dd>{new Date(paymentTime(transaction) * 1000).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</dd></div>
      </dl>
      <div className="provider-receipt-block"><p>Payment trail</p><div><span>Agent → OpenMCP</span><ReceiptLink receipt={transaction.agent_to_openmcp} label="agent payment" /></div><div><span>OpenMCP → provider</span><ReceiptLink receipt={transaction.openmcp_to_provider} label="provider payment" /></div></div>
      {transaction.error && <p className="provider-detail-error">{transaction.error.message}</p>}
      <div className="provider-detail-id"><span className="mono">{transaction.execution_id}</span><CopyButton value={transaction.execution_id} label="request ID" /></div>
      <p className="provider-fine-print">Tempo Moderato testnet. These tokens have no monetary value.</p>
    </>}
  </dialog>;
}

const navigation: { id: ProviderView; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "payments", label: "Payments", icon: "payments" },
  { id: "services", label: "Services", icon: "services" },
  { id: "wallets", label: "Wallets", icon: "wallets" },
];

const headings: Record<ProviderView, { title: string; description: string }> = {
  overview: { title: "Your data, earning.", description: "A clear view of the value your services create." },
  payments: { title: "Every payment, accounted for.", description: "Follow each request from agent payment to provider receipt." },
  services: { title: "Useful data. Open for business.", description: "Your registered services, prices, and earnings in one place." },
  wallets: { title: "Straight to your wallet.", description: "Confirmed balances and the addresses that receive your payments." },
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
  const [announcement, setAnnouncement] = useState("");
  const seenReceipts = useRef<Set<string> | null>(null);

  useEffect(() => {
    const readHash = () => {
      const hash = window.location.hash.slice(1);
      const match = navigation.find(item => item.id === hash);
      if (match) setView(match.id);
    };
    readHash();
    window.addEventListener("hashchange", readHash);
    return () => window.removeEventListener("hashchange", readHash);
  }, []);

  useEffect(() => {
    if (!data) return;
    const received = data.transactions.filter(isReceived);
    const latest = received.filter(transaction => !seenReceipts.current?.has(transaction.execution_id));
    if (seenReceipts.current && latest.length) {
      setAnnouncement(`${latest.length === 1 ? `${latest[0].provider} received` : `${latest.length} new payments received ·`} +${money(latest.reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0))} test pathUSD`);
    }
    seenReceipts.current = new Set(received.map(transaction => transaction.execution_id));
  }, [data]);

  useEffect(() => {
    if (!announcement) return;
    const timer = setTimeout(() => setAnnouncement(""), 6000);
    return () => clearTimeout(timer);
  }, [announcement]);

  const now = updatedAt ?? 0;
  const providers = data?.providers.filter(item => provider === "all" || item.endpoint_id === provider) ?? [];
  const transactions = scopedTransactions(data, provider, period, now);
  const received = transactions.filter(isReceived);
  const pending = transactions.filter(transaction => !isReceived(transaction) && transaction.status !== "quoted");
  const net = received.reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
  const fees = received.reduce((sum, transaction) => sum + transaction.platform_fee_cents, 0);
  const pendingAmount = pending.reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
  const gross = received.reduce((sum, transaction) => sum + transaction.price_cents, 0);
  const allEarnings = (data?.transactions ?? []).filter(transaction => isReceived(transaction) && (provider === "all" || transaction.endpoint_id === provider)).reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
  const sessionEarnings = providers.reduce((sum, item) => sum + item.session_earned_cents, 0);
  const filtered = transactions.filter(transaction => {
    const matchesFilter = filter === "all" || (filter === "received" ? isReceived(transaction) : !isReceived(transaction));
    return matchesFilter && `${transaction.provider} ${transaction.endpoint_id} ${transaction.execution_id} ${transaction.openmcp_to_provider?.reference ?? ""}`.toLowerCase().includes(search.toLowerCase());
  });
  const pageCount = Math.max(1, Math.ceil(filtered.length / 8));
  const currentPage = Math.min(page, pageCount - 1);
  const selected = data?.transactions.find(transaction => transaction.execution_id === selectedId) ?? null;
  const providerName = data?.providers.find(item => item.endpoint_id === provider)?.name ?? "All providers";
  const periodLabel = period === "all" ? "All time" : `Last ${period} days`;

  function exportPayments() {
    const blob = new Blob(["\uFEFF", paymentsCsv(filtered)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `openmcp-payments-${provider}-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function paymentTable(compact = false) {
    const rows = compact ? transactions.slice(0, 5) : filtered.slice(currentPage * 8, currentPage * 8 + 8);
    return <>
      <div className="provider-table-scroll"><table className="provider-table"><caption className="provider-sr-only">{compact ? "Recent payments" : "Provider payments"} in test pathUSD</caption><thead><tr><th scope="col">Service / provider</th><th scope="col">Status</th><th scope="col">{compact ? "Date" : "Agent paid"}</th><th scope="col" className="provider-align-right">{compact ? "Net amount" : "Fee"}</th>{!compact && <th scope="col" className="provider-align-right">Net amount</th>}<th scope="col"><span className="provider-sr-only">Details</span></th></tr></thead><tbody>
        {rows.map(transaction => <tr key={transaction.execution_id} className={isReceived(transaction) ? "" : "provider-pending-row"}>
          <td><div className="provider-table-identity"><ProviderMark name={transaction.provider} small /><div><span>{transaction.provider}</span><code>/{transaction.endpoint_id}</code></div></div></td>
          <td><span className={`provider-status ${isReceived(transaction) ? "received" : "pending"}`}>{isReceived(transaction) && <Icon name="check" size={12} />}{paymentLabel(transaction)}</span></td>
          <td className={compact ? "muted" : "provider-numeric"}>{compact ? new Date(paymentTime(transaction) * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : money(transaction.price_cents)}</td>
          <td className={`provider-align-right provider-numeric ${compact && isReceived(transaction) ? "provider-positive" : "muted"}`}>{compact ? `${isReceived(transaction) ? "+" : ""}${money(transaction.provider_amount_cents)}` : money(transaction.platform_fee_cents)}</td>
          {!compact && <td className={`provider-align-right provider-numeric ${isReceived(transaction) ? "provider-positive" : "muted"}`}>{isReceived(transaction) ? "+" : ""}{money(transaction.provider_amount_cents)}</td>}
          <td><button type="button" className="provider-icon-button" onClick={() => setSelectedId(transaction.execution_id)} aria-label={`View payment from ${transaction.provider}, ${money(transaction.provider_amount_cents)} test pathUSD`}><Icon name="arrow" size={16} /></button></td>
        </tr>)}
      </tbody></table></div>
      {rows.length === 0 && <div className="provider-empty"><div className="provider-empty-icon"><Icon name="payments" size={23} /></div><h3>{!data ? "Waiting for the connection" : search || filter !== "all" ? "No matching payments" : "Ready for your first payment"}</h3><p>{!data ? "Your payment history will appear when the local stack connects." : search || filter !== "all" ? "Try another search or payment status." : "When an agent pays for your service, you’ll see it here."}</p>{data && !search && filter === "all" && <Link href="/demo" className="provider-inline-link">Open the FreightFlow demo <Icon name="arrow" size={15} /></Link>}</div>}
      {!compact && <div className="provider-pagination"><span>{filtered.length ? `${currentPage * 8 + 1}–${Math.min((currentPage + 1) * 8, filtered.length)} of ${filtered.length} payments` : "0 payments"}</span><div><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><button type="button" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>Next</button></div></div>}
    </>;
  }

  function walletCard(service: ProviderService) {
    const balance = service.wallet_balance;
    const total = (data?.transactions ?? []).filter(transaction => transaction.endpoint_id === service.endpoint_id && isReceived(transaction)).reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
    return <article className="provider-wallet-card" key={service.endpoint_id}><div className="provider-section-heading"><div className="provider-service-heading"><ProviderMark name={service.name} /><h2>{service.name}</h2></div><Icon name="wallets" /></div><p className="provider-card-label">On-chain balance</p><div className="provider-wallet-amount"><WalletTicker balance={balance} /></div><div className="provider-address"><code title={service.address}>{service.address}</code><CopyButton value={service.address} label={`${service.name} wallet address`} /></div><dl className="provider-wallet-summary"><div><dt>All-time ledger earnings</dt><dd><NumberTicker value={total / 100} decimalPlaces={2} /> <span>test pathUSD</span></dd></div><div><dt>Current session earnings</dt><dd><NumberTicker value={service.session_earned_cents / 100} decimalPlaces={2} /> <span>test pathUSD</span></dd></div><div><dt>Network</dt><dd>Tempo Moderato</dd></div></dl>{balance?.error && <p className="provider-detail-error">Balance unavailable. The network read will retry automatically.</p>}<a className="provider-inline-link" href={`https://explore.moderato.tempo.xyz/address/${service.address}`} target="_blank" rel="noreferrer">View wallet on explorer <Icon name="external" size={14} /></a></article>;
  }

  return <div className="provider-app">
    <a href="#provider-main" className="skip-link">Skip to content</a>
    <aside className="provider-sidebar">
      <Brand />
      <div className="provider-workspace"><span className="provider-workspace-icon"><Icon name="services" /></span><div><span>Provider workspace</span><small>OpenMCP network</small></div></div>
      <p className="provider-nav-label">WORKSPACE</p>
      <nav aria-label="Provider dashboard">{navigation.map(item => <a key={item.id} href={`#${item.id}`} className={view === item.id ? "active" : ""} aria-current={view === item.id ? "page" : undefined}><Icon name={item.icon} /><span>{item.label}</span>{item.id === "services" && data && <small>{data.providers.length}</small>}</a>)}</nav>
      <div className="provider-sidebar-bottom"><div className="provider-brand-card"><Image src="/images/lavender-temple.jpeg" alt="" width={360} height={170} unoptimized /><div><p>Built for useful data.</p><span>Paid for every exchange.</span><Link href="/demo">See it in motion <Icon name="arrow" size={14} /></Link></div></div><Link href="/" className="provider-back">← Back to OpenMCP</Link><div className="provider-environment"><span />Test environment<small>Valueless tokens</small></div></div>
    </aside>

    <div className="provider-workspace-main">
      <header className="provider-topbar"><div className="provider-breadcrumb">Workspace <span>/</span> <strong>{navigation.find(item => item.id === view)?.label}</strong></div><div className="provider-topbar-actions"><span className={`provider-live ${error ? "offline" : !data ? "connecting" : ""}`}><i />{error ? "Connection interrupted" : data ? "Live" : "Connecting"}</span><Link href="/demo">Agent demo <Icon name="external" size={13} /></Link><span className="provider-avatar" title="Local provider workspace">O</span></div></header>
      <div className="provider-money-strip"><span>Provider earnings <strong>{data ? <NumberTicker value={allEarnings / 100} decimalPlaces={2} /> : "—"}</strong><small>test pathUSD · all time</small></span><span>Agent budget left <strong>{data ? <NumberTicker value={data.agent.remaining_cents / 100} decimalPlaces={2} /> : "—"}</strong><small>test pathUSD · current session</small></span></div>

      <main id="provider-main" className="provider-main">
        <div className="provider-page-heading"><div><p className="eyebrow">PROVIDER {view.toUpperCase()}</p><h1>{headings[view].title}</h1><p>{headings[view].description}</p></div><button type="button" className="provider-secondary-button" onClick={exportPayments} disabled={!data || filtered.length === 0}><Icon name="download" size={16} />Export payments</button></div>
        <div className="provider-toolbar"><div className="provider-filters"><label className="provider-select"><Icon name="services" size={16} /><span className="provider-sr-only">Provider</span><select value={provider} onChange={event => { setProvider(event.target.value); setPage(0); }}><option value="all">All providers</option>{data?.providers.map(item => <option key={item.endpoint_id} value={item.endpoint_id}>{item.name}</option>)}</select></label><label className="provider-select"><span className="provider-sr-only">Reporting period</span><select value={period} onChange={event => { setPeriod(event.target.value as Period); setPage(0); }}><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="all">All time</option></select></label></div><div className="provider-update"><span>{updatedAt ? `Updated ${new Date(updatedAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}` : "Connecting to OpenMCP"}</span><button type="button" className="provider-icon-button" onClick={refresh} disabled={refreshing} aria-label="Refresh provider data"><Icon name="refresh" size={15} /></button></div></div>
        {error && <div className="provider-connection-error" role="alert"><Icon name="refresh" /><div><strong>{data ? "Connection interrupted — showing last received data" : "Your local stack is offline"}</strong><p>{error}</p></div><button type="button" onClick={refresh} disabled={refreshing}>Retry</button></div>}

        {(view === "overview" || view === "payments") && <div className="provider-metrics">
          <section className="provider-metric primary"><div className="provider-metric-label"><span>Net earnings</span><Icon name="payments" size={17} /></div><div className="provider-metric-value">{data ? <NumberTicker value={net / 100} decimalPlaces={2} /> : "—"}<span>test pathUSD</span></div><p><span className="provider-dot" />{periodLabel} · after platform fees</p></section>
          <section className="provider-metric"><div className="provider-metric-label"><span>Payments received</span><Icon name="check" size={17} /></div><div className="provider-metric-value">{data ? <NumberTicker value={received.length} /> : "—"}<span>payments</span></div><p>{data ? `${money(gross)} test pathUSD in agent purchases` : "Waiting for payment records"}</p></section>
          <section className="provider-metric"><div className="provider-metric-label"><span>Pending earnings</span><Icon name="wallets" size={17} /></div><div className="provider-metric-value">{data ? <NumberTicker value={pendingAmount / 100} decimalPlaces={2} /> : "—"}<span>test pathUSD</span></div><p>{pending.length ? `${pending.length} ${pending.length === 1 ? "payment awaiting" : "payments awaiting"} confirmation` : data ? "You’re all caught up" : "Waiting for payment records"}</p></section>
        </div>}

        {view === "overview" && <>
          <div className="provider-overview-grid"><section className="provider-panel provider-earnings"><div className="provider-section-heading"><div><h2>Earnings over time</h2><p>{periodLabel} · {providerName}</p></div><span className="provider-unit-label">Net earnings</span></div><EarningsChart transactions={transactions} period={period} now={now} loaded={Boolean(data)} /></section>
            <section className="provider-panel provider-breakdown"><div className="provider-section-heading"><h2>The payment split</h2><Icon name="payments" /></div><p>Useful data. A simple exchange.</p><div className="provider-split-amount">{data ? <NumberTicker value={gross / 100} decimalPlaces={2} /> : "—"}<span>test pathUSD paid by agents</span></div><div className="provider-split-bar" aria-label={`${money(net)} provider earnings and ${money(fees)} platform fees`}><span style={{ width: `${gross ? net / gross * 100 : 0}%` }} /></div><dl><div><dt><i />Provider earnings</dt><dd>{data ? <NumberTicker value={net / 100} decimalPlaces={2} /> : "—"}</dd></div><div><dt><i />OpenMCP fees</dt><dd>{data ? <NumberTicker value={fees / 100} decimalPlaces={2} /> : "—"}</dd></div></dl><div className="provider-settlement-note"><Icon name="wallets" size={17} /><span>Payments settle directly to your provider wallet.</span></div></section></div>
          <section className="provider-panel provider-payment-panel"><div className="provider-section-heading"><div><h2>Recent payments</h2><p>Each receipt is a little more value unlocked.</p></div><a href="#payments" className="provider-inline-link">View all payments <Icon name="arrow" size={15} /></a></div>{paymentTable(true)}</section>
          <section className="provider-service-strip"><div><h2>Your services</h2><p>{data ? `${providers.length} registered ${providers.length === 1 ? "endpoint" : "endpoints"}` : "Connecting"}</p></div><div>{providers.map(service => <a href="#services" key={service.endpoint_id} onClick={() => setProvider(service.endpoint_id)}><ProviderMark name={service.name} small /><span>{service.name}<small>{money(service.provider_amount_cents)} per call</small></span><Icon name="arrow" size={14} /></a>)}</div></section>
        </>}

        {view === "payments" && <section className="provider-panel provider-payment-panel"><div className="provider-section-heading"><div><h2>Payment history</h2><p>Amounts in test pathUSD. Pending amounts are expected, not settled.</p></div></div><div className="provider-payment-filters"><div className="provider-filter-tabs" aria-label="Payment status">{(["all", "received", "pending"] as PaymentFilter[]).map(value => <button key={value} type="button" aria-pressed={filter === value} className={filter === value ? "active" : ""} onClick={() => { setFilter(value); setPage(0); }}>{value === "all" ? "All payments" : value === "received" ? "Received" : "Pending"}</button>)}</div><label className="provider-search"><Icon name="search" size={16} /><input aria-label="Search payments" placeholder="Search payments…" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} /></label></div>{paymentTable()}</section>}

        {view === "services" && <div className="provider-service-grid">{providers.map(service => {
          const servicePayments = received.filter(transaction => transaction.endpoint_id === service.endpoint_id);
          const earnings = servicePayments.reduce((sum, transaction) => sum + transaction.provider_amount_cents, 0);
          return <article className="provider-service-card" key={service.endpoint_id}><div className="provider-section-heading"><ProviderMark name={service.name} /><span className="provider-status received">Registered</span></div><h2>{service.name}</h2><p>{service.description}</p><div className="provider-endpoint"><span>POST</span><code>{service.endpoint_path}</code><CopyButton value={service.endpoint_path} label="endpoint path" /></div><div className="provider-service-pricing"><div><span>Agent pays</span><strong>{money(service.price_cents)}</strong></div><div><span>You receive</span><strong>{money(service.provider_amount_cents)}</strong></div><div><span>Platform fee</span><strong>{money(service.platform_fee_cents)}</strong></div></div><p className="provider-fine-print">test pathUSD per request</p><div className="provider-service-performance"><span>{periodLabel}<strong><NumberTicker value={servicePayments.length} /> payments</strong></span><span>Net earnings<strong><NumberTicker value={earnings / 100} decimalPlaces={2} /> <small>test pathUSD</small></strong></span></div><a className="provider-inline-link" href="#payments" onClick={() => { setProvider(service.endpoint_id); setSearch(""); setFilter("all"); setPage(0); }}>View payments <Icon name="arrow" size={15} /></a></article>;
        })}{!data && <div className="provider-empty"><h2>Connecting to your services</h2><p>Registered endpoints will appear when the local stack is available.</p></div>}</div>}

        {view === "wallets" && <><div className="provider-wallet-notice"><Icon name="wallets" /><p>Wallet balances include earlier payments and testnet funding. Ledger earnings track payments recorded by this OpenMCP instance. Network fees can make these amounts differ.</p></div><div className="provider-wallet-grid">{providers.map(walletCard)}{!data && <div className="provider-empty"><h2>Connecting to your wallets</h2><p>Balances are read directly from Tempo testnet.</p></div>}</div><div className="provider-agent-card"><div><p className="eyebrow">CURRENT AGENT SESSION</p><h2>{data ? <NumberTicker value={data.agent.remaining_cents / 100} decimalPlaces={2} /> : "—"} <span>test pathUSD remaining</span></h2><p>Of {data ? money(data.agent.budget_cents) : "—"} service budget · <NumberTicker value={sessionEarnings / 100} decimalPlaces={2} /> earned by {providerName.toLowerCase()} this session</p></div><div><span className="mono">{shortAddress(data?.agent.address)}</span><span>Wallet balance: <WalletTicker balance={data?.agent.wallet_balance} /></span></div></div></>}

        <footer className="provider-footer"><span><i />Tempo testnet · valueless test tokens</span><span>Payments powered by OpenMCP <span className="provider-footer-symbol">↗</span></span></footer>
      </main>
    </div>
    <div className={`provider-toast ${announcement ? "visible" : ""}`} role="status" aria-live="polite">{announcement && <><span><Icon name="check" size={16} /></span>{announcement}</>}</div>
    <PaymentDetail transaction={selected} onClose={() => setSelectedId(null)} />
  </div>;
}
