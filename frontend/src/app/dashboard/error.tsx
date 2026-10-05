"use client";
import Link from "next/link";
export default function AccountError({ reset }: { reset: () => void }) {
  return <section className="account-empty"><h2>Your account could not be loaded.</h2><p>Please retry. If your session has ended, sign in again.</p><div className="account-button-row"><button className="button" onClick={reset}>Retry</button><Link href="/sign-in" className="account-secondary">Sign in</Link></div></section>;
}
