import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  turbopack: { root: process.cwd() },
  async redirects() {
    return [
      { source: "/demo/:path*", destination: "/dashboard", permanent: true },
      { source: "/providers/:path*", destination: "/dashboard", permanent: true },
    ];
  },
};
export default nextConfig;
