"use client";
import { Button } from "@/components/ui/button";
import { DashboardFrame } from "./dashboard-frame";
import { Alert } from "@/components/ui/alert";

import { Show, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { accountRequest, type Account } from "@/lib/account";
import { ErrorNotice, Loading } from "./common";

const AccountContext = createContext<{
  account: Account;
  publicApiOrigin: string | null;
} | null>(null);
export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("Account context unavailable");
  return value;
}
export function AccountShell({
  children,
  userId,
  publicApiOrigin,
}: {
  children: React.ReactNode;
  userId: string;
  publicApiOrigin: string | null;
}) {
  const router = useRouter();
  const identity = useAuth();
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // The server layout belongs to one verified identity. Replace it after a
    // Clerk session switch before showing or fetching another user's account.
    if (identity.isLoaded && identity.userId && identity.userId !== userId)
      router.refresh();
  }, [identity.isLoaded, identity.userId, userId, router]);
  useEffect(() => {
    const controller = new AbortController();
    setAccount(null);
    setError(null);
    if (!identity.isLoaded || identity.userId !== userId) return;
    accountRequest<Account>("/me/bootstrap", {
      method: "POST",
      body: {},
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setAccount(result);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught);
      });
    return () => controller.abort();
  }, [userId, identity.userId, identity.isLoaded, attempt]);
  return (
    <>
      <Show when="signed-out">
        <div className="account-setup">
          <h1>Your session has ended.</h1>
          <Button asChild>
            <Link href="/sign-in">Sign in again</Link>
          </Button>
        </div>
      </Show>
      <Show when="signed-in">
        {identity.userId !== userId && <Loading text="Switching accounts…" />}
        {identity.userId === userId && (
          <DashboardFrame mode={account?.mode} userMenu={<UserButton />}>
            {error ? (
              <ErrorNotice
                error={error}
                retry={() => setAttempt((value) => value + 1)}
              />
            ) : !account ? (
              <Loading />
            ) : (
              <AccountContext.Provider value={{ account, publicApiOrigin }}>
                {account.mode === "test" && (
                  <Alert
                    role="status"
                    className="account-notice account-test-notice"
                  >
                    Test mode · Payments use Stripe test mode. These are test
                    credits.
                  </Alert>
                )}
                {account.status !== "active" && (
                  <Alert className="account-notice error" role="status">
                    Your account is restricted. New purchases are paused while a
                    funding issue is resolved. Your history remains available.
                  </Alert>
                )}
                {children}
              </AccountContext.Provider>
            )}
          </DashboardFrame>
        )}
      </Show>
    </>
  );
}
