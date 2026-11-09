/**
 * Keeps pictures, signed links and secrets out of error reports.
 *
 * Photos of shoppers must never reach an error tracker. The app never sends one on purpose; this is the net
 * underneath. Applied to every event and breadcrumb by `sentryOptions`. Mirrors `app/core/redact.py` in the API.
 * This file exists in both apps (kiosk and admin) and a test keeps the copies identical.
 */
const DATA_URI = /data:[\w/+.-]+;base64,[A-Za-z0-9+/_\-=]*/gi;
const BLOB_URL = /blob:[^\s"')]+/gi; // an object URL of a captured photo
const LONG_RUN = /[A-Za-z0-9+/_-]{120,}={0,2}/g; // an encoded image is far longer than any legitimate token
const SIGNED = /([?&])(X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|Signature|AWSAccessKeyId)=[^&\s"'<>]+/gi;
const MOBILE_CODE = /(\/m\/)[A-Za-z0-9%]{4,20}/g;
const MAX_FIELD_CHARS = 2000;

export function redactText(text: string): string {
  return text
    .replace(DATA_URI, "data:[image removed]")
    .replace(BLOB_URL, "blob:[removed]")
    .replace(SIGNED, "$1$2=[redacted]")
    .replace(MOBILE_CODE, "$1[code]")
    .replace(LONG_RUN, "[blob removed]");
}

export function redactDeep<T>(value: T, depth = 0): T {
  if (depth > 12) return value;
  if (typeof value === "string") {
    const out = redactText(value);
    return (out.length > MAX_FIELD_CHARS ? `${out.slice(0, MAX_FIELD_CHARS)}...[truncated]` : out) as T;
  }
  if (Array.isArray(value)) return value.map((v) => redactDeep(v, depth + 1)) as T;
  if (value && typeof value === "object") {
    if (typeof Blob !== "undefined" && value instanceof Blob) return `<${(value as Blob).size} bytes>` as T;
    if (value instanceof ArrayBuffer) return `<${value.byteLength} bytes>` as T;
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, redactDeep(v, depth + 1)])) as T;
  }
  return value;
}

type Frame = { vars?: unknown };
type LooseEvent = {
  user?: unknown;
  request?: Record<string, unknown>;
  exception?: { values?: { stacktrace?: { frames?: Frame[] } }[] };
};

/** The `beforeSend` hook: drops request data, cookies, headers and users, and redacts every string left. */
export function scrubEvent<T extends object>(event: T): T {
  const e = event as LooseEvent;
  delete e.user;
  if (e.request) {
    for (const field of ["cookies", "data", "headers", "query_string"]) delete e.request[field];
  }
  for (const exc of e.exception?.values ?? []) {
    for (const frame of exc.stacktrace?.frames ?? []) delete frame.vars;
  }
  return redactDeep(event);
}

export function scrubBreadcrumb<T extends object>(crumb: T): T {
  return redactDeep(crumb);
}
