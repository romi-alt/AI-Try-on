import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: { instrumentationHook: true }, // loads src/instrumentation.ts (Sentry on the server)
  output: "standalone",
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
