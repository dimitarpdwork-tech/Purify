/** @type {import('next').NextConfig} */
// NOTE: rewrites are resolved when `next build` runs, so API_INTERNAL_URL must be
// present at build time (the Dockerfile exposes it as a build arg).
const API = (process.env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/+$/, "");

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // CSV/XLSX uploads and exports can be slow; the default proxy timeout is 30s.
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
