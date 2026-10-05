"use client";
import Link from "next/link";
import { use, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { localDate, money, safeExternalUrl, transactionLabels, type Execution, type Transaction } from "@/lib/account";
import { ErrorNotice, Loading, Status, useResource } from "@/components/account/common";

function Result({ id }: { id: string }) {
  const execution = useResource<Execution>(`/executions/${encodeURIComponent(id)}`, data => ["reserved", "payment_pending", "fulfillment_pending"].includes(data.status));
  if (execution.loading) return <Loading text="Loading service result…"/>;
  if (execution.error) return <ErrorNotice error={execution.error} retry={execution.reload}/>;
  if (!execution.data) return null;
  const result = execution.data; const receipt = safeExternalUrl(result.provider_receipt?.explorer_url);
  const json = result.data == null ? null : JSON.stringify(result.data, null, 2);
  function download() {
    if (!json) return;
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" })); const link = document.createElement("a");
    link.href = url; link.download = `openmcp-${result.execution_id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="account-panel account-detail-panel"><div className="account-panel-heading"><h2>Service result</h2><Status value={result.status}/></div>{result.status === "refunded" && <div className="account-notice">{money(result.refunded_cents)} was returned to your wallet. This purchase no longer consumes your agent’s allowance.</div>}{["reserved", "payment_pending", "fulfillment_pending", "needs_review"].includes(result.status) && <div className="account-notice">{result.status === "needs_review" ? "This payment needs review. Any unresolved spending remains reserved until its outcome is confirmed." : "Your purchase is still processing. Reserved credits remain pending until the outcome is confirmed."}</div>}{result.error?.message && <p className="account-detail-message">{result.error.message}</p>}{json && result.status === "completed" && <><div className="account-result-toolbar"><span>JSON result</span><button className="account-secondary" onClick={download}>Download JSON</button></div><pre className="account-result-preview">{json.length > 20_000 ? `${json.slice(0, 20_000)}\n… Download the complete result.` : json}</pre></>}{receipt && <a className="account-inline-link" href={receipt} target="_blank" rel="noopener noreferrer">View provider receipt ↗</a>}</section>;
}
function Detail({ id }: { id: string }) {
  const params = useSearchParams(); const requestedBack = params.get("return") ?? "";
  const back = /^\/dashboard\/transactions(?:\?[^#]*)?$/.test(requestedBack) ? requestedBack : "/dashboard/transactions";
  const row = useResource<Transaction>(`/transactions/${encodeURIComponent(id)}`, data => data.status === "pending");
  return <><Link className="account-inline-link account-back-link" href={back}>← Back to transactions</Link>{row.loading ? <Loading text="Loading transaction…"/> : row.error ? <ErrorNotice error={row.error} retry={row.reload}/> : row.data && <><div className="account-page-heading"><div><span className="eyebrow">{transactionLabels[row.data.type].toUpperCase()}</span><h1>{row.data.description || transactionLabels[row.data.type]}</h1><p>{localDate(row.data.created_at)} · local time</p></div><Status value={row.data.status}/></div><section className="account-panel account-detail-panel"><div className="account-detail-amount">{row.data.amount_cents > 0 ? "+" : ""}{money(row.data.amount_cents)}<span>USD credits</span></div><dl className="account-detail-grid"><div><dt>Status</dt><dd>{row.data.status === "refunded" ? "Credits returned to wallet" : row.data.status === "needs_review" ? "Payment outcome under review" : row.data.status === "pending" ? "Awaiting confirmation" : row.data.status === "failed" ? "Not completed" : "Completed"}</dd></div><div><dt>Balance after transaction</dt><dd>{row.data.balance_after_cents == null ? "Not settled" : money(row.data.balance_after_cents)}</dd></div>{row.data.agent_name && <div><dt>Agent</dt><dd>{row.data.agent_name}</dd></div>}{row.data.endpoint_id && <div><dt>Service</dt><dd>{row.data.endpoint_id}</dd></div>}<div className="account-detail-wide"><dt>Transaction ID</dt><dd><code>{row.data.id}</code></dd></div></dl>{row.data.related_transaction_id && <Link className="account-inline-link" href={`/dashboard/transactions/${encodeURIComponent(row.data.related_transaction_id)}?return=${encodeURIComponent(back)}`}>View related transaction →</Link>}{safeExternalUrl(row.data.receipt_url) && <a className="account-inline-link" href={safeExternalUrl(row.data.receipt_url)!} target="_blank" rel="noopener noreferrer">View payment receipt ↗</a>}</section>{row.data.execution_id && <Result id={row.data.execution_id}/>}</>}</>;
}
export default function TransactionDetail({ params }: { params: Promise<{ id: string }> }) { const { id } = use(params); return <Suspense fallback={<Loading/>}><Detail id={id}/></Suspense>; }
