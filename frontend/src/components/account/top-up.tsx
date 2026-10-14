"use client";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { LockKeyhole, LoaderCircle } from "lucide-react";

import { useId, useRef, useState } from "react";
import {
  accountRequest,
  checkoutIntent,
  errorMessage,
  money,
  parseTopUpAmount,
  readCheckoutIntent,
  safeExternalUrl,
  TOP_UP_MAX_CENTS,
  TOP_UP_MIN_CENTS,
  type CheckoutIntent,
  type TopUp,
} from "@/lib/account";
import { useAccount } from "./shell";
import { Icon, Modal } from "./common";

export function AddMoneyDialog({
  presets,
  mode,
  busy = false,
  error,
  onClose,
  onCheckout,
}: {
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

  return (
    <Modal
      title="Add money"
      onClose={onClose}
      busy={busy}
      className="account-top-up-dialog"
    >
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          setTouched(true);
          if (!busy && amount !== null) onCheckout(amount);
        }}
      >
        <p className="account-top-up-intro">
          Fund your wallet. Pay for only what your agents use.
        </p>
        <div className={`account-amount-entry${invalid ? " is-invalid" : ""}`}>
          <div className="account-amount-label">
            <Label htmlFor={inputId}>Amount to add</Label>
            <span>USD</span>
          </div>
          <div className="account-amount-value">
            <span aria-hidden="true">$</span>
            <Input
              variant="bare"
              id={inputId}
              name="amount"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
              aria-label="Amount to add in US dollars"
              aria-describedby={`${inputId}-hint`}
              aria-invalid={invalid}
              disabled={busy}
              value={value}
              placeholder="0.00"
              maxLength={9}
              onChange={(event) => setValue(event.target.value)}
              onBlur={() => setTouched(true)}
              onFocus={(event) => event.currentTarget.select()}
            />
          </div>
          <p
            id={`${inputId}-hint`}
            className="account-amount-hint"
            aria-live="polite"
          >
            {invalid
              ? `Enter ${money(TOP_UP_MIN_CENTS)}–${money(TOP_UP_MAX_CENTS)}, with up to 2 decimal places.`
              : `$${TOP_UP_MIN_CENTS / 100}–$${TOP_UP_MAX_CENTS / 100} per top-up.`}
          </p>
        </div>
        <ToggleGroup
          type="single"
          value={amount === null ? "" : String(amount)}
          onValueChange={(value) => {
            if (value) {
              setValue((Number(value) / 100).toFixed(2));
              setTouched(false);
            }
          }}
          className="account-top-up-presets"
          disabled={busy}
          spacing={2}
          aria-label="Suggested amounts"
        >
          {presets.map((preset) => (
            <ToggleGroupItem key={preset} value={String(preset)}>
              ${preset / 100}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <div className="account-top-up-receipt">
          <div>
            <span>Wallet credit</span>
            <small>Available after payment</small>
          </div>
          <strong>{amount === null ? "—" : money(amount)}</strong>
        </div>
        {mode === "test" && (
          <p className="account-inline-warning">
            This deployment accepts test payments only.
          </p>
        )}
        {error && (
          <p className="account-form-error" role="alert">
            {error}
          </p>
        )}
        <Button
          variant="default"
          className="button account-top-up-submit"
          type="submit"
          disabled={busy || amount === null}
        >
          {busy ? (
            <>
              <LoaderCircle
                className="size-4 animate-spin"
                aria-hidden="true"
              />
              Preparing checkout…
            </>
          ) : (
            <>
              Continue to checkout
              <Icon name="arrow" size={18} />
            </>
          )}
        </Button>
        <div className="account-top-up-trust">
          <LockKeyhole size={13} strokeWidth={1.6} aria-hidden="true" />
          <span>
            Secured by <strong>Stripe</strong>
          </span>
          <span aria-hidden="true">·</span>
          <span>
            Card or <strong>Link</strong>
          </span>
        </div>
      </form>
    </Modal>
  );
}

export function AddMoney({ onClose }: { onClose: () => void }) {
  const { account } = useAccount();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intent = useRef<CheckoutIntent | null>(null);
  const lock = useRef(false);
  async function checkout(amount: number) {
    if (lock.current || !amount) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    const storageKey = `openmcp-top-up-intent:${account.account_id}`;
    try {
      if (!intent.current) {
        try {
          intent.current = readCheckoutIntent(
            sessionStorage.getItem(storageKey),
          );
        } catch {
          /* Storage is optional; the in-memory retry key still works. */
        }
      }
      intent.current = checkoutIntent(intent.current, amount);
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(intent.current));
      } catch {
        /* Private browsing may disable storage. */
      }
      const topUp = await accountRequest<TopUp>("/wallet/top-ups", {
        method: "POST",
        body: { amount_cents: amount },
        key: intent.current.key,
      });
      intent.current = { ...intent.current, topUpId: topUp.id };
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(intent.current));
      } catch {
        /* Storage is optional. */
      }
      const checkoutUrl = safeExternalUrl(topUp.checkout_url, true);
      if (["credited", "processing", "creating"].includes(topUp.status)) {
        window.location.assign(
          `/dashboard/top-up/return?top_up_id=${encodeURIComponent(topUp.id)}`,
        );
        return;
      }
      if (["failed", "expired"].includes(topUp.status)) {
        intent.current = null;
        try {
          sessionStorage.removeItem(storageKey);
        } catch {
          /* Optional storage. */
        }
        throw new Error(
          "This checkout is no longer available. Please retry to start a new one.",
        );
      }
      if (!checkoutUrl)
        throw new Error(
          "The checkout link is not ready. Retry to retrieve the same payment safely.",
        );
      // Keep the key until the return page: a reload before redirect still reuses this checkout.
      window.location.assign(checkoutUrl);
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
      lock.current = false;
    }
  }
  return (
    <AddMoneyDialog
      presets={account.top_up_presets_cents}
      mode={account.mode}
      busy={busy}
      error={error}
      onClose={onClose}
      onCheckout={checkout}
    />
  );
}
