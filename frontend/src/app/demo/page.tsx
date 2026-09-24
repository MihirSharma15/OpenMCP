import type { Metadata } from "next";
import Demo from "./demo";
import "./demo.css";

export const metadata: Metadata = {
  title: "OpenMCP — Wallet observer",
  description:
    "Observe an OpenMCP budget, wallet balance, and recent transaction receipts.",
};

export default function DemoPage() { return <Demo />; }
