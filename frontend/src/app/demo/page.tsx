import type { Metadata } from "next";
import Demo from "./demo";
import "./demo.css";

export const metadata: Metadata = { title: "OpenMCP — FreightFlow live demo", description: "Watch an agent buy three fictional data sources through six real MPP payments on Tempo testnet." };

export default function DemoPage() { return <Demo />; }
