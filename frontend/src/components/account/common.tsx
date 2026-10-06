"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AccountApiError, accountRequest, errorMessage, localDate, money, statusLabels, transactionLabels, type Transaction } from "@/lib/account";

export function Icon({ name, size = 20 }: { name: "wallet" | "history" | "agent" | "arrow" | "plus" | "close" | "check"; size?: number }) {
  const paths = {
    wallet: <><path d="M20 8V5a2 2 0 0 0-2-2H6a3 3 0 0 0 0 6h14v11H6a3 3 0 0 1-3-3V6"/><path d="M20 12h-5v4h5"/></>,
    history: <><path d="M3 11a9 9 0 1 1 2.3 7M3 4v7h7"/><path d="M12 7v5l3 2"/></>,
    agent: <><rect x="4" y="6" width="16" height="14" rx="4"/><path d="M12 2v4M8 11v2m8-2v2M9 16h6M1 11v4m22-4v4"/></>,
    arrow: <><path d="M5 12h14m-5-5 5 5-5 5"/></>, plus: <path d="M12 5v14M5 12h14"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>, check: <path d="m5 12 4 4L19 6"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
export function Status({ value }: { value: string }) { return <span className={`account-status status-${value}`}>{statusLabels[value] ?? value.replaceAll("_", " ")}</span>; }
export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  const expired = error instanceof AccountApiError && error.status === 401;
  return <div className="account-notice error" role="alert"><div><strong>{expired ? "Sign in to continue" : "We could not update this information"}</strong><p>{errorMessage(error)}</p>{error instanceof AccountApiError && error.requestId && <small>Reference: {error.requestId}</small>}</div>{expired ? <Link className="account-secondary" href="/sign-in">Sign in</Link> : retry && <button className="account-secondary" onClick={retry}>Retry</button>}</div>;
}
export function Loading({ text = "Loading your account…" }: { text?: string }) { return <div className="account-loading" role="status"><span className="account-spinner"/>{text}</div>; }
export function Empty({ icon = "history", title, children }: { icon?: "wallet" | "history" | "agent"; title: string; children: React.ReactNode }) {
  return <div className="account-empty"><span className="account-empty-icon"><Icon name={icon} size={24}/></span><h3>{title}</h3><div>{children}</div></div>;
}
export function Modal({ title, children, onClose, busy = false, className = "" }: { title: string; children: React.ReactNode; onClose: () => void; busy?: boolean; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog ref={ref} className={`account-dialog ${className}`} aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}><div className="account-dialog-heading"><h2>{title}</h2><button aria-label="Close dialog" disabled={busy} className="account-icon-button" onClick={onClose}><Icon name="close" /></button></div>{children}</dialog>;
}
export function useResource<T>(path: string, pending?: (data: T) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const pendingRef = useRef(pending); pendingRef.current = pending;
  const reload = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    // An agent can spend while the user is working in another app. Revalidate
    // when they return, including when no purchase was pending on the last read.
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>; let attempts = 0;
    setData(null); setLoading(true); setError(null);
    const load = async () => {
      try {
        const result = await accountRequest<T>(path, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setData(result); setError(null);
        if (pendingRef.current?.(result) && attempts++ < 12) timer = setTimeout(load, Math.min(3000 * 1.4 ** attempts, 30_000));
      } catch (caught) { if (!controller.signal.aborted) setError(caught); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, version]);
  return { data, error, loading, reload };
}

export function TransactionTable({ rows, returnPath = "/dashboard/transactions" }: { rows: Transaction[]; returnPath?: string }) {
  return <div className="account-table-scroll"><table className="account-table"><thead><tr><th scope="col">Transaction</th><th scope="col">Date</th><th scope="col">Status</th><th scope="col" className="account-number">Amount</th><th scope="col"><span className="account-sr-only">Details</span></th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><div className="account-transaction-name"><span className={`account-transaction-icon type-${row.type}`}>{row.type === "deposit" || row.type === "refund" ? "↙" : "↗"}</span><div><strong>{row.description || transactionLabels[row.type]}</strong><span>{transactionLabels[row.type]}{row.agent_name ? ` · ${row.agent_name}` : ""}</span></div></div></td><td className="account-date">{localDate(row.created_at)}</td><td><Status value={row.status}/></td><td className={`account-number ${row.amount_cents > 0 ? "account-positive" : ""}`}>{row.amount_cents > 0 ? "+" : ""}{money(row.amount_cents)}</td><td><Link className="account-row-link" aria-label={`View ${row.description || transactionLabels[row.type]}`} href={`/dashboard/transactions/${encodeURIComponent(row.id)}?return=${encodeURIComponent(returnPath)}`}><Icon name="arrow" size={18}/></Link></td></tr>)}</tbody></table></div>;
}
