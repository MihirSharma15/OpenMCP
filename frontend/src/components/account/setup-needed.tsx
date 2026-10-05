import Link from "next/link";

export function SetupNeeded() {
  return <main className="account-setup"><Link href="/" className="wordmark">OpenMCP</Link><div className="account-setup-card"><span className="eyebrow accent">Your wallet, connected</span><h1>Sign-in is being configured.</h1><p>Account access is not available on this deployment yet. Your wallet and transaction history will be available here once sign-in is ready.</p><Link href="/" className="button">Back to OpenMCP</Link></div></main>;
}
