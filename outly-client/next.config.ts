import type { NextConfig } from "next";

// Server-side only (not NEXT_PUBLIC_*) — the actual backend the proxy forwards to.
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/backend", destination: `${BACKEND_URL}/` },
      { source: "/backend/:path*", destination: `${BACKEND_URL}/:path*` },
    ];
  },
};

export default nextConfig;
