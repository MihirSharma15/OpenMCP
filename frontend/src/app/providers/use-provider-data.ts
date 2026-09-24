"use client";

import { useEffect, useState } from "react";
import { fetchProviderOverview, type ProviderOverview, RunnerApiError } from "@/lib/openmcp";

export function useProviderData() {
  const [data, setData] = useState<ProviderOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(true);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    let nextChainRead = 0;
    let first = true;

    async function poll() {
      // Render the ledger first; the following poll adds on-chain balances.
      const chain = !first && Date.now() >= nextChainRead;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 20_000);
      try {
        const next = await fetchProviderOverview(chain, controller.signal);
        if (!active) return;
        setData(previous => chain ? next : {
          ...next,
          agent: { ...next.agent, wallet_balance: previous?.agent.wallet_balance },
          providers: next.providers.map(provider => ({
            ...provider,
            wallet_balance: previous?.providers.find(item => item.address === provider.address)?.wallet_balance,
          })),
        });
        if (chain) nextChainRead = Date.now() + 5000;
        setUpdatedAt(Date.now());
        setError(null);
      } catch (caught) {
        if (!active) return;
        setError(caught instanceof RunnerApiError ? caught.message : "The connection timed out. We’ll keep trying automatically.");
      } finally {
        window.clearTimeout(timeout);
        if (active) {
          first = false;
          setRefreshing(false);
          timer = setTimeout(poll, 1000);
        }
      }
    }
    void poll();
    return () => {
      active = false;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [refreshKey]);

  return { data, error, updatedAt, refreshing, refresh: () => {
    setRefreshing(true);
    setRefreshKey(key => key + 1);
  } };
}
