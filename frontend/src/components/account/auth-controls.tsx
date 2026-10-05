"use client";
import { Show, UserButton } from "@clerk/nextjs";
import Link from "next/link";

export function AuthControls({ enabled }: { enabled: boolean }) {
  if (!enabled) return <><Link href="/sign-in">Sign in</Link><Link href="/dashboard" className="button button-small">Get started</Link></>;
  return <><Show when="signed-out"><Link href="/sign-in">Sign in</Link><Link href="/sign-up" className="button button-small">Get started</Link></Show><Show when="signed-in"><Link href="/dashboard" className="button button-small">Dashboard</Link><UserButton /></Show></>;
}
