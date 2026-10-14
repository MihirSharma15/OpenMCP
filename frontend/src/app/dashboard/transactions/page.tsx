"use client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { SelectField } from "@/components/select-field";

import { Suspense, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  accountRequest,
  statusLabels,
  transactionLabels,
  type Page,
  type Transaction,
} from "@/lib/account";
import {
  Empty,
  ErrorNotice,
  Loading,
  TransactionTable,
  useResource,
} from "@/components/account/common";

function History() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  const query = new URLSearchParams({
    limit: "20",
    ...(type ? { type } : {}),
    ...(status ? { status } : {}),
  }).toString();
  const activeQuery = useRef(query);
  activeQuery.current = query;
  const page = useResource<Page<Transaction>>(
    `/transactions?${query}`,
    (data) => data.items.some((row) => row.status === "pending"),
  );
  const [extra, setExtra] = useState<Transaction[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<unknown>(null);
  useEffect(() => {
    setExtra([]);
    setCursor(page.data?.next_cursor ?? null);
    setMoreError(null);
  }, [page.data]);
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`);
  }
  async function more() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const result = await accountRequest<Page<Transaction>>(
        `/transactions?${query}&cursor=${encodeURIComponent(cursor)}`,
      );
      if (activeQuery.current === query) {
        setExtra((previous) => [...previous, ...result.items]);
        setCursor(result.next_cursor);
      }
    } catch (error) {
      if (activeQuery.current === query) setMoreError(error);
    } finally {
      setLoadingMore(false);
    }
  }
  const rows = [
    ...new Map(
      [...(page.data?.items ?? []), ...extra].map((row) => [row.id, row]),
    ).values(),
  ];
  return (
    <>
      <div className="account-page-heading">
        <div>
          <h1>Transactions</h1>
          <p>Every deposit, purchase, and refund. All in one ledger.</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="account-secondary"
          onClick={page.reload}
        >
          Refresh
        </Button>
      </div>
      <Card as="section" className="account-panel">
        <div className="account-filters">
          <Label>
            Type
            <SelectField
              value={type || "all"}
              label="Transaction type"
              className="w-full"
              onValueChange={(value) =>
                filter("type", value === "all" ? "" : value)
              }
              options={[
                { value: "all", label: "All transactions" },
                ...Object.entries(transactionLabels).map(([value, label]) => ({
                  value,
                  label,
                })),
              ]}
            />
          </Label>
          <Label>
            Status
            <SelectField
              value={status || "all"}
              label="Transaction status"
              className="w-full"
              onValueChange={(value) =>
                filter("status", value === "all" ? "" : value)
              }
              options={[
                { value: "all", label: "All statuses" },
                ...[
                  "pending",
                  "completed",
                  "failed",
                  "refunded",
                  "needs_review",
                ].map((value) => ({ value, label: statusLabels[value] })),
              ]}
            />
          </Label>
          {(type || status) && (
            <Button
              variant="link"
              size="sm"
              className="account-link-button"
              onClick={() => router.replace(pathname)}
            >
              Clear filters
            </Button>
          )}
        </div>
        {Boolean(page.error) && (
          <ErrorNotice error={page.error} retry={page.reload} />
        )}{" "}
        {page.loading ? (
          <Loading text="Loading transactions…" />
        ) : rows.length ? (
          <TransactionTable
            rows={rows}
            returnPath={`${pathname}${params.size ? `?${params}` : ""}`}
          />
        ) : (
          page.data && (
            <Empty
              title={
                type || status
                  ? "No matching transactions"
                  : "No transactions yet"
              }
            >
              <p>
                {type || status
                  ? "Try another filter to see more of your wallet’s history."
                  : "Add money or let your agent buy its first service. The details will appear here."}
              </p>
            </Empty>
          )
        )}
        {Boolean(moreError) && <ErrorNotice error={moreError} retry={more} />}{" "}
        {cursor && (
          <div className="account-load-more">
            <Button
              variant="outline"
              size="sm"
              className="account-secondary"
              disabled={loadingMore}
              onClick={more}
            >
              {loadingMore ? "Loading…" : "Load more"}
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
export default function TransactionsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <History />
    </Suspense>
  );
}
