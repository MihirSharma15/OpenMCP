"use client";

import type { WalletBalance } from "@/lib/openmcp";
import { NumberTicker } from "./number-ticker";

export function WalletTicker({ balance }: { balance: WalletBalance | undefined }) {
  if (!balance || balance.error) return <>Unavailable</>;
  const amount = balance.balance !== undefined
    ? Number(balance.balance)
    : typeof balance.balance_units === "number" && typeof balance.decimals === "number"
      ? balance.balance_units / 10 ** balance.decimals
      : NaN;
  if (!Number.isFinite(amount)) return <>Unavailable</>;
  const tokenLabel = !balance.token || balance.token === "pathUSD" ? "USD" : balance.token;
  return <><NumberTicker value={amount} decimalPlaces={2} /> {tokenLabel}</>;
}
