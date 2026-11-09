import { scrubBreadcrumb, scrubEvent } from "./sentryScrub";

/**
 * The Sentry settings shared by the browser, the server and the edge runtime. Privacy first:
 * no personal data, no session replay (it would record the shopper's face on screen), no request bodies, and no
 * trace headers on API calls (the API's CORS would refuse them). Sentry is only started when a DSN is set.
 */
export function sentryOptions(dsn: string | undefined) {
  return {
    dsn,
    enabled: !!dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? process.env.NODE_ENV,
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || undefined,
    sendDefaultPii: false,
    maxBreadcrumbs: 30,
    tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? 0),
    tracePropagationTargets: [] as string[],
    // A mirror that loses its connection throws these constantly; the connectivity monitor already handles it.
    ignoreErrors: ["Failed to fetch", "NetworkError when attempting to fetch resource", "Load failed", "AbortError"],
    beforeSend: <T extends object>(event: T): T => scrubEvent(event),
    beforeSendTransaction: <T extends object>(event: T): T => scrubEvent(event),
    beforeBreadcrumb: <T extends object>(crumb: T): T => scrubBreadcrumb(crumb),
  };
}
