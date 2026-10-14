import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";

export function SetupNeeded() {
  return (
    <main className="account-setup">
      <Link href="/" className="wordmark">
        OpenMCP
      </Link>
      <Card className="account-setup-card">
        <span className="eyebrow accent">Your wallet, connected</span>
        <h1>Sign-in is being configured.</h1>
        <p>
          Account access is not available on this deployment yet. Your wallet
          and transaction history will be available here once sign-in is ready.
        </p>
        <Button asChild variant="default">
          <Link href="/" className="button">
            Back to OpenMCP
          </Link>
        </Button>
      </Card>
    </main>
  );
}
