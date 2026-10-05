import type { NextConfig } from "next";

const runnerUrl = new URL(
  process.env.OPENMCP_DEMO_RUNNER_URL ?? "http://127.0.0.1:8100",
);
if (
  runnerUrl.protocol !== "http:" ||
  !["127.0.0.1", "localhost"].includes(runnerUrl.hostname) ||
  (runnerUrl.pathname !== "/" && runnerUrl.pathname !== "")
) {
  throw new Error("OPENMCP_DEMO_RUNNER_URL must be a local HTTP origin");
}

const nextConfig: NextConfig = {
  devIndicators: false,
  turbopack: { root: process.cwd() },
  async redirects() {
    // The hosted product serves account pages; legacy observers remain local.
    return process.env.VERCEL === "1" ? [
      { source: "/demo/:path*", destination: "/dashboard", permanent: true },
      { source: "/providers/:path*", destination: "/dashboard", permanent: true },
    ] : [];
  },
  rewrites() {
    if (process.env.VERCEL === "1") return [];
    return [
      {
        source: "/api/runner/:path*",
        destination: `${runnerUrl.origin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
