import type { Metadata } from "next";
import Demo from "./demo";
import "./demo.css";

export const metadata: Metadata = { title: "OpenMCP — FreightFlow demo", description: "Watch an agent run due diligence with a $15 budget. Three services, three payments, one report." };

export default function DemoPage() { return <Demo />; }
