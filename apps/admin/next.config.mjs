import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: { instrumentationHook: true }, // loads src/instrumentation.ts (Sentry on the server)
  // The Docker image uses the standalone server; on Vercel (VERCEL=1) Vercel builds its own output.
  async headers() {
    return [
      {
        source: "/((?!_next/static|_next/image|favicon.ico).*)", // not the build's immutable assets
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
          { key: "Cache-Control", value: "no-store" }, // signed-in pages and API data are never cached by a browser or CDN
        ],
      },
    ];
  },
  output: process.env.VERCEL ? undefined : "standalone",
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
