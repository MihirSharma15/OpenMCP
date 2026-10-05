"use client";
import Link from "next/link";
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { money, readCheckoutIntent, returnedCheckoutMatches, safeExternalUrl, topUpPending, type TopUp } from "@/lib/account";
import { Empty, ErrorNotice, Icon, Loading, Status, useResource } from "@/components/account/common";
import { useAccount } from "@/components/account/shell";

function PaymentStatus({ id, canceled }: { id: string; canceled: boolean }) {
  const { account } = useAccount();
  const payment = useResource<TopUp>(`/wallet/top-ups/${encodeURIComponent(id)}`, data => topUpPending(data.status));
  useEffect(() => {
    if (!payment.data) return;
    try {
      const key = `openmcp-top-up-intent:${account.account_id}`;
      if (returnedCheckoutMatches(readCheckoutIntent(sessionStorage.getItem(key)), payment.data)) sessionStorage.removeItem(key);
    } catch { /* Storage is optional. */ }
  }, [payment.data, account.account_id]);
  const status = payment.data?.status;
  const resumeUrl = status === "awaiting_payment" ? safeExternalUrl(payment.data?.checkout_url, true) : null;
  const titles: Record<string, string> = { creating: "Getting your payment ready.", awaiting_payment: "Waiting for your payment.", processing: "Confirming your payment.", credited: "Your wallet is ready.", failed: "Your payment did not complete.", expired: "This checkout has expired." };
  return <section className="account-return-card">{payment.loading ? <Loading text="Checking your payment…"/> : payment.error ? <ErrorNotice error={payment.error} retry={payment.reload}/> : payment.data && <><span className={`account-return-icon ${status === "credited" ? "success" : ""}`}><Icon name={status === "credited" ? "check" : "wallet"} size={32}/></span><Status value={payment.data.status}/><h1>{titles[payment.data.status]}</h1><p>{status === "credited" ? `${money(payment.data.amount_cents)} has been added to your OpenMCP wallet. Your agents can now use these credits within their allowances.` : status === "failed" || status === "expired" ? "No credits were added for this checkout. You can start a new payment from your dashboard." : "Credits become available after Stripe confirms the payment. We’ll check for updates automatically for a few minutes; you can return here at any time."}</p>{canceled && status !== "credited" && <div className="account-notice">You returned from checkout. We’re checking its actual payment status; returning here does not cancel a payment already in progress.</div>}<div className="account-return-amount"><span>Top-up amount</span><strong>{money(payment.data.amount_cents)}</strong></div><div className="account-button-row"><Link className="button" href="/dashboard">Back to wallet</Link>{resumeUrl && <a className="account-secondary" href={resumeUrl}>Resume checkout ↗</a>}{topUpPending(payment.data.status) && <button className="account-secondary" onClick={payment.reload}>Check again</button>}</div><small className="account-helper">Payment reference: {payment.data.id}</small></>}</section>;
}
function ReturnContent() {
  const params = useSearchParams(); const id = params.get("top_up_id");
  if (!id || !/^[A-Za-z0-9_-]{1,160}$/.test(id)) return <Empty icon="wallet" title="Payment reference missing"><p>Open your wallet to check the latest balance and activity.</p><Link href="/dashboard" className="button">Back to wallet</Link></Empty>;
  return <PaymentStatus id={id} canceled={params.get("canceled") === "1"}/>;
}
export default function TopUpReturn() { return <Suspense fallback={<Loading/>}><ReturnContent/></Suspense>; }
