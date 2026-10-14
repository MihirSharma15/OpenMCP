import { notFound } from "next/navigation";
import DashboardPreview from "./preview";
import "../../dashboard/account.css";
import "../../dashboard/dashboard.css";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Dashboard preview — OpenMCP",
  robots: { index: false, follow: false },
};

export default function DashboardPreviewPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DashboardPreview now={Date.now()} />;
}
