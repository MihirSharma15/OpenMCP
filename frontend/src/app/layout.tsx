import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { clerkConfigured } from "@/lib/account-config";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenMCP — Unlimited APIs. One Wallet.",
  description: "Fund one wallet, give your AI agent a spending limit, and pay for useful services as you go. Every purchase and refund in one place.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/figtree-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/geist-mono-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body>{clerkConfigured() ? <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up" signInFallbackRedirectUrl="/dashboard" signUpFallbackRedirectUrl="/dashboard" appearance={{ variables: { colorPrimary: "#6259A6", fontFamily: "Figtree, sans-serif", borderRadius: "12px" } }}>{children}</ClerkProvider> : children}</body>
    </html>
  );
}
