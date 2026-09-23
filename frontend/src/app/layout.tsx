import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenMCP — Unlimited APIs. One Wallet.",
  description: "OpenMCP turns any API or MCP server into a pay-as-you-go service. Agents find you, pay per request, and get your data back.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="preload" href="/fonts/figtree-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/fonts/geist-mono-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  );
}
