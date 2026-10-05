"use client";
import { Show, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { accountRequest, type Account } from "@/lib/account";
import { ErrorNotice, Icon, Loading } from "./common";

const AccountContext = createContext<{ account: Account; publicApiOrigin: string | null } | null>(null);
export function useAccount() { const value = useContext(AccountContext); if (!value) throw new Error("Account context unavailable"); return value; }
export function AccountShell({ children, userId, publicApiOrigin }: { children: React.ReactNode; userId: string; publicApiOrigin: string | null }) {
  const pathname = usePathname(); const router = useRouter(); const identity = useAuth();
  const [account, setAccount] = useState<Account | null>(null); const [error, setError] = useState<unknown>(null); const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    // The server layout belongs to one verified identity. Replace it after a
    // Clerk session switch before showing or fetching another user's account.
    if (identity.isLoaded && identity.userId && identity.userId !== userId) router.refresh();
  }, [identity.isLoaded, identity.userId, userId, router]);
  useEffect(() => {
    const controller = new AbortController(); setAccount(null); setError(null);
    if (!identity.isLoaded || identity.userId !== userId) return;
    accountRequest<Account>("/me/bootstrap", { method: "POST", body: {}, signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) setAccount(result);
    }).catch(caught => { if (!controller.signal.aborted) setError(caught); });
    return () => controller.abort();
  }, [userId, identity.userId, identity.isLoaded, attempt]);
  const navigation = [{ href: "/dashboard", title: "Overview", icon: "wallet" }, { href: "/dashboard/transactions", title: "Transactions", icon: "history" }, { href: "/dashboard/agents", title: "Agents", icon: "agent" }] as const;
  return <><Show when="signed-out"><div className="account-setup"><h1>Your session has ended.</h1><Link href="/sign-in" className="button">Sign in again</Link></div></Show><Show when="signed-in">{identity.userId !== userId && <Loading text="Switching accounts…"/>}{identity.userId === userId && <div className="account-app"><a className="skip-link" href="#account-main">Skip to content</a><aside className="account-sidebar"><Link href="/" className="wordmark"><span className="account-brand-mark">↗</span>OpenMCP</Link><div className="account-workspace"><span className="account-avatar">P</span><div>Personal wallet<span>Your agent workspace</span></div></div><nav aria-label="Account">{navigation.map(item => <Link key={item.href} href={item.href} className={(item.href === "/dashboard" ? pathname === item.href : pathname.startsWith(item.href)) ? "active" : ""} aria-current={(item.href === "/dashboard" ? pathname === item.href : pathname.startsWith(item.href)) ? "page" : undefined}><Icon name={item.icon}/>{item.title}</Link>)}</nav><div className="account-sidebar-note"><Icon name="agent"/><p>A little allowance.<br/>A lot of possibility.</p><span>You set the limit. Your agent brings back the results.</span></div><div className="account-sidebar-footer"><span>Personal account</span><UserButton /></div></aside><div className="account-content"><header className="account-topbar"><span>Workspace <span className="account-breadcrumb">/ {navigation.find(item => item.href !== "/dashboard" && pathname.startsWith(item.href))?.title ?? "Overview"}</span></span><span className="account-environment">{account?.mode === "test" ? "Test mode" : account?.mode === "live" ? "Live" : "Connecting"}<span className={`account-dot ${account?.mode === "live" ? "live" : ""}`}/></span></header><main id="account-main" className="account-main">{error ? <ErrorNotice error={error} retry={() => setAttempt(value => value + 1)}/> : !account ? <Loading/> : <AccountContext.Provider value={{ account, publicApiOrigin }}>{account.mode === "test" && <div className="account-notice account-test-notice">Test mode · Payments here use Stripe test mode. Funds are test credits.</div>}{account.status !== "active" && <div className="account-notice error" role="status">Your account is restricted. New purchases are paused while a funding issue is resolved. Your history remains available.</div>}{children}</AccountContext.Provider>}</main><footer className="account-footer"><span>One wallet. Useful things.</span><span>OpenMCP · USD credits</span></footer></div></div>}</Show></>;
}
