import { notFound } from "next/navigation";
import DesignSystem from "./playground";
import "../dashboard/account.css";
import "./playground.css";

export default function DesignSystemPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DesignSystem />;
}
