"use client";
import { useRef, useState } from "react";
import { accountRequest, checkoutIntent, errorMessage, money, readCheckoutIntent, safeExternalUrl, type CheckoutIntent, type TopUp } from "@/lib/account";
import { useAccount } from "./shell";
import { Modal } from "./common";

export function AddMoney({ onClose }: { onClose: () => void }) {
  const { account } = useAccount();
  const [amount, setAmount] = useState(account.top_up_presets_cents.includes(1000) ? 1000 : account.top_up_presets_cents[0]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const intent = useRef<CheckoutIntent | null>(null);
  const lock = useRef(false);
  async function checkout() {
    if (lock.current || !amount) return;
    lock.current = true; setBusy(true); setError(null);
    const storageKey = `openmcp-top-up-intent:${account.account_id}`;
    try {
      if (!intent.current) {
        try { intent.current = readCheckoutIntent(sessionStorage.getItem(storageKey)); } catch { /* Storage is optional; the in-memory retry key still works. */ }
      }
      intent.current = checkoutIntent(intent.current, amount);
      try { sessionStorage.setItem(storageKey, JSON.stringify(intent.current)); } catch { /* Private browsing may disable storage. */ }
      const topUp = await accountRequest<TopUp>("/wallet/top-ups", { method: "POST", body: { amount_cents: amount }, key: intent.current.key });
      intent.current = { ...intent.current, topUpId: topUp.id };
      try { sessionStorage.setItem(storageKey, JSON.stringify(intent.current)); } catch { /* Storage is optional. */ }
      const checkoutUrl = safeExternalUrl(topUp.checkout_url, true);
      if (["credited", "processing", "creating"].includes(topUp.status)) {
        window.location.assign(`/dashboard/top-up/return?top_up_id=${encodeURIComponent(topUp.id)}`); return;
      }
      if (["failed", "expired"].includes(topUp.status)) {
        intent.current = null; try { sessionStorage.removeItem(storageKey); } catch { /* Optional storage. */ }
        throw new Error("This checkout is no longer available. Please retry to start a new one.");
      }
      if (!checkoutUrl) throw new Error("The checkout link is not ready. Retry to retrieve the same payment safely.");
      // Keep the key until the return page: a reload before redirect still reuses this checkout.
      window.location.assign(checkoutUrl);
    } catch (caught) { setError(errorMessage(caught)); setBusy(false); lock.current = false; }
  }
  return <Modal title="Add money" onClose={onClose} busy={busy}><p className="account-dialog-copy">Add USD credits to your wallet. Your agent can spend only within the allowance you give it.</p><fieldset className="account-amount-options" disabled={busy}><legend>Choose an amount</legend>{account.top_up_presets_cents.map(value => <label key={value} className={amount === value ? "selected" : ""}><input type="radio" name="top-up-amount" value={value} checked={amount === value} onChange={() => setAmount(value)}/>{money(value)}</label>)}</fieldset><div className="account-checkout-summary"><span>You’ll receive</span><strong>{amount ? money(amount) : "—"} in credits</strong></div><p className="account-helper">Secure checkout with Stripe. Pay by card, or with Link when available. Credits appear after your payment is confirmed.</p>{account.mode === "test" && <p className="account-inline-warning">This deployment accepts test payments only.</p>}{error && <p className="account-form-error" role="alert">{error}</p>}<button className="button account-full-button" disabled={busy || !amount} onClick={checkout}>{busy ? "Preparing checkout…" : "Continue to Stripe"}<span aria-hidden="true"> ↗</span></button></Modal>;
}
