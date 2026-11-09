import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: { instrumentationHook: true }, // loads src/instrumentation.ts (Sentry on the server)
  output: "standalone",
  async headers() {
    return [
      // The service worker file itself must always be re-checked, or a fixed worker would never reach the mirror.
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }, { key: "Service-Worker-Allowed", value: "/" }] },
    ];
  },
  images: {
    // Media comes from MinIO locally and R2 in production; allow any https host
    // plus the local MinIO port. Tighten this once the public R2 domain is known.
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
      { protocol: "http", hostname: "minio" },
      { protocol: "https", hostname: "**" },
    ],
  },
};

// Error reporting stays off until NEXT_PUBLIC_SENTRY_DSN is set. Source maps are only uploaded when a Sentry auth
// token is present at build time (SENTRY_AUTH_TOKEN, with SENTRY_ORG and SENTRY_PROJECT); otherwise nothing is
// uploaded and the build makes no network calls to Sentry.
export default withSentryConfig(nextConfig, {
  silent: true,
  telemetry: false,
  disableLogger: true,
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  hideSourceMaps: true,
});
