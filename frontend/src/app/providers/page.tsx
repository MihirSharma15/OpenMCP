import type { Metadata } from "next";
import Providers from "./providers";
import "./providers.css";

export const metadata: Metadata = {
  title: "Provider dashboard — OpenMCP",
  description: "Follow your API earnings, incoming payments, and provider wallet balances on OpenMCP.",
};

export default function ProvidersPage() {
  return <Providers />;
}
