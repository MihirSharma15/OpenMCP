import { auth } from "@clerk/nextjs/server";
import { clerkConfigured } from "@/lib/account-config";
import { apiOrigin } from "@/lib/account-proxy";
import { SetupNeeded } from "@/components/account/setup-needed";
import { AccountShell } from "@/components/account/shell";
import "./account.css";

export const dynamic = "force-dynamic";
export const metadata = { title: "Your wallet — OpenMCP", robots: { index: false, follow: false } };
export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  if (!clerkConfigured()) return <SetupNeeded />;
  const { userId } = await auth.protect();
  const publicApiOrigin = apiOrigin(process.env.OPENMCP_PUBLIC_API_URL ?? process.env.OPENMCP_API_URL);
  return <AccountShell key={userId} userId={userId} publicApiOrigin={publicApiOrigin}>{children}</AccountShell>;
}
