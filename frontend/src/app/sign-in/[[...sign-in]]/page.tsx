import { SignIn } from "@clerk/nextjs";
import Link from "next/link";
import { clerkConfigured } from "@/lib/account-config";
import { SetupNeeded } from "@/components/account/setup-needed";
import "../../dashboard/account.css";

export default function SignInPage() {
  if (!clerkConfigured()) return <SetupNeeded />;
  return <main className="account-auth"><Link href="/" className="wordmark">OpenMCP</Link><SignIn path="/sign-in" routing="path" signUpUrl="/sign-up" fallbackRedirectUrl="/dashboard" /></main>;
}
