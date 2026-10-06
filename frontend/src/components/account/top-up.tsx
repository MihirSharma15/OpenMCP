"use client";
import { useId, useRef, useState } from "react";
import { accountRequest, checkoutIntent, errorMessage, money, parseTopUpAmount, readCheckoutIntent, safeExternalUrl, TOP_UP_MAX_CENTS, TOP_UP_MIN_CENTS, type CheckoutIntent, type TopUp } from "@/lib/account";
import { useAccount } from "./shell";
import { Icon, Modal } from "./common";

export function AddMoneyDialog({ presets, mode, busy = false, error, onClose, onCheckout }: {
  presets: number[];
  mode: "test" | "live";
  busy?: boolean;
  error?: string | null;
  onClose: () => void;
  onCheckout: (amountCents: number) => void;
}) {
  const [value, setValue] = useState("10.00");
  const [touched, setTouched] = useState(false);
  const inputId = useId();
  const amount = parseTopUpAmount(value);
  const invalid = touched && amount === null;

  return <Modal title="Add money" onClose={onClose} busy={busy} className="account-top-up-dialog">
    <form noValidate onSubmit={event => {
      event.preventDefault(); setTouched(true);
      if (!busy && amount !== null) onCheckout(amount);
    }}>
      <div className={`account-amount-entry${invalid ? " is-invalid" : ""}`}>
        <div className="account-amount-label">
          <label htmlFor={inputId}>Amount to add</label>
          <span>USD</span>
        </div>
        <div className="account-amount-value">
          <span aria-hidden="true">$</span>
          <input id={inputId} name="amount" type="text" inputMode="decimal" autoComplete="off"
            spellCheck={false} aria-label="Amount to add in US dollars" aria-describedby={`${inputId}-hint`}
            aria-invalid={invalid} disabled={busy} value={value} placeholder="0.00" maxLength={9}
            style={{ width: `${Math.max(2, value.length || 4)}ch` }}
            onChange={event => setValue(event.target.value)} onBlur={() => setTouched(true)}
            onFocus={event => event.currentTarget.select()} />
        </div>
        <p id={`${inputId}-hint`} className="account-amount-hint" aria-live="polite">
          {invalid ? `Enter ${money(TOP_UP_MIN_CENTS)}–${money(TOP_UP_MAX_CENTS)}, with up to 2 decimal places.` : `$${TOP_UP_MIN_CENTS / 100}–$${TOP_UP_MAX_CENTS / 100} per top-up.`}
        </p>
      </div>
      <fieldset className="account-top-up-presets" disabled={busy}>
        <legend className="account-sr-only">Suggested amounts</legend>
        {presets.map(preset => <button key={preset} type="button" aria-pressed={amount === preset}
          onClick={() => { setValue((preset / 100).toFixed(2)); setTouched(false); }}>
          ${preset / 100}
        </button>)}
      </fieldset>
      <div className="account-top-up-receipt">
        <span className="account-top-up-wallet"><Icon name="wallet" size={19}/></span>
        <div><span>Added to your wallet</span><small>Ready to use after payment</small></div>
        <strong>{amount === null ? "—" : money(amount)}</strong>
      </div>
      {mode === "test" && <p className="account-inline-warning">This deployment accepts test payments only.</p>}
      {error && <p className="account-form-error" role="alert">{error}</p>}
      <button className="button account-top-up-submit" type="submit" disabled={busy || amount === null}>
        {busy ? <><span className="account-spinner"/>Preparing checkout…</> : <>Continue to checkout<Icon name="arrow" size={18}/></>}
      </button>
      <div className="account-top-up-trust">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/></svg>
        <span>Secured by <strong>Stripe</strong></span><span aria-hidden="true">·</span><span>Card or <strong>Link</strong></span>
      </div>
    </form>
  </Modal>;
}

export function AddMoney({ onClose }: { onClose: () => void }) {
  const { account } = useAccount();
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const intent = useRef<CheckoutIntent | null>(null);
  const lock = useRef(false);
  async function checkout(amount: number) {
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
  return <AddMoneyDialog presets={account.top_up_presets_cents} mode={account.mode} busy={busy} error={error} onClose={onClose} onCheckout={checkout}/>;
}
