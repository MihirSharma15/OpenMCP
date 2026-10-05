import { SignUp } from "@clerk/nextjs";
import Link from "next/link";
import { clerkConfigured } from "@/lib/account-config";
import { SetupNeeded } from "@/components/account/setup-needed";
import "../../dashboard/account.css";

export default function SignUpPage() {
  if (!clerkConfigured()) return <SetupNeeded />;
  return <main className="account-auth"><Link href="/" className="wordmark">OpenMCP</Link><SignUp path="/sign-up" routing="path" signInUrl="/sign-in" fallbackRedirectUrl="/dashboard" /></main>;
}
