"use client";
import { Icon } from "@/components/icons";
export { Icon } from "@/components/icons";

import { Badge } from "@/components/ui/badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Empty as EmptyState,
  EmptyHeader,
  EmptyTitle,
  EmptyMedia,
  EmptyContent,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccountApiError,
  accountRequest,
  errorMessage,
  localDate,
  money,
  statusLabels,
  transactionLabels,
  type Transaction,
} from "@/lib/account";

export function Status({ value }: { value: string }) {
  return (
    <Badge className={`account-status status-${value}`}>
      {statusLabels[value] ?? value.replaceAll("_", " ")}
    </Badge>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const expired = error instanceof AccountApiError && error.status === 401;
  return (
    <Alert className="account-notice error" role="alert">
      <div>
        <strong>
          {expired
            ? "Sign in to continue"
            : "We could not update this information"}
        </strong>
        <p>{errorMessage(error)}</p>
        {error instanceof AccountApiError && error.requestId && (
          <small>Reference: {error.requestId}</small>
        )}
      </div>
      {expired ? (
        <Button asChild variant="outline" size="sm">
          <Link className="account-secondary" href="/sign-in">
            Sign in
          </Link>
        </Button>
      ) : (
        retry && (
          <Button
            variant="outline"
            size="sm"
            className="account-secondary"
            onClick={retry}
          >
            Retry
          </Button>
        )
      )}
    </Alert>
  );
}
export function Loading({ text = "Loading your account…" }: { text?: string }) {
  return (
    <div className="account-loading" role="status">
      <div aria-hidden="true" className="flex w-full max-w-sm flex-col gap-3">
        <Skeleton className="h-3 w-1/3" />
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="h-3 w-full" />
      </div>
      <span className="sr-only">{text}</span>
    </div>
  );
}
export function Empty({
  icon = "history",
  title,
  children,
}: {
  icon?: "wallet" | "history" | "agent";
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <EmptyState className="account-empty">
      <EmptyHeader>
        <EmptyMedia variant="icon" className="account-empty-icon">
          <Icon name={icon} size={24} />
        </EmptyMedia>
        {title && <EmptyTitle>{title}</EmptyTitle>}
      </EmptyHeader>
      <EmptyContent>{children}</EmptyContent>
    </EmptyState>
  );
}
export function Modal({
  title,
  children,
  onClose,
  busy = false,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  busy?: boolean;
  className?: string;
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent
        className={`account-dialog ${className}`}
        showCloseButton={false}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (busy) event.preventDefault();
        }}
      >
        <div className="account-dialog-heading">
          <DialogTitle>{title}</DialogTitle>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Close dialog"
            disabled={busy}
            className="account-icon-button"
            onClick={onClose}
          >
            <Icon name="close" />
          </Button>
        </div>
        <DialogDescription className="sr-only">
          {title}. Review the details below before continuing.
        </DialogDescription>
        {children}
      </DialogContent>
    </Dialog>
  );
}
export function useResource<T>(path: string, pending?: (data: T) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    // An agent can spend while the user is working in another app. Revalidate
    // when they return, including when no purchase was pending on the last read.
    window.addEventListener("focus", reload);
    return () => window.removeEventListener("focus", reload);
  }, [reload]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let attempts = 0;
    setData(null);
    setLoading(true);
    setError(null);
    const load = async () => {
      try {
        const result = await accountRequest<T>(path, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setData(result);
        setError(null);
        if (pendingRef.current?.(result) && attempts++ < 12)
          timer = setTimeout(load, Math.min(3000 * 1.4 ** attempts, 30_000));
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, version]);
  return { data, error, loading, reload };
}

export function TransactionTable({
  rows,
  returnPath = "/dashboard/transactions",
  onView,
}: {
  rows: Transaction[];
  returnPath?: string;
  onView?: (transaction: Transaction) => void;
}) {
  return (
    <div className="account-table-scroll">
      <Table className="account-table">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Transaction</TableHead>
            <TableHead scope="col">Date</TableHead>
            <TableHead scope="col">Status</TableHead>
            <TableHead scope="col" className="account-number">
              Amount
            </TableHead>
            <TableHead scope="col">
              <span className="account-sr-only">Details</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <div className="account-transaction-name">
                  <span className={`account-transaction-icon type-${row.type}`}>
                    {row.type === "deposit" || row.type === "refund"
                      ? "↙"
                      : "↗"}
                  </span>
                  <div>
                    <strong>
                      {row.description || transactionLabels[row.type]}
                    </strong>
                    <span>
                      {transactionLabels[row.type]}
                      {row.agent_name ? ` · ${row.agent_name}` : ""}
                    </span>
                    <div className="account-transaction-mobile-meta">
                      <Status value={row.status} />
                      <time dateTime={row.created_at}>
                        {new Date(row.created_at).toLocaleDateString(
                          undefined,
                          { month: "short", day: "numeric" },
                        )}
                      </time>
                    </div>
                  </div>
                </div>
              </TableCell>
              <TableCell className="account-date">
                {localDate(row.created_at)}
              </TableCell>
              <TableCell>
                <Status value={row.status} />
              </TableCell>
              <TableCell
                className={`account-number ${row.amount_cents > 0 ? "account-positive" : ""}`}
              >
                {row.amount_cents > 0 ? "+" : ""}
                {money(row.amount_cents)}
              </TableCell>
              <TableCell>
                {onView ? (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`View ${row.description || transactionLabels[row.type]}`}
                    onClick={() => onView(row)}
                  >
                    <Icon name="arrow" size={18} />
                  </Button>
                ) : (
                  <Link
                    className="account-row-link"
                    aria-label={`View ${row.description || transactionLabels[row.type]}`}
                    href={`/dashboard/transactions/${encodeURIComponent(row.id)}?return=${encodeURIComponent(returnPath)}`}
                  >
                    <Icon name="arrow" size={18} />
                  </Link>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
