/**
 * Slows down password guessing: after `maxFailures` failed sign-ins for the same email within `windowMs`, further
 * attempts are refused until the oldest failure ages out. In memory, so it resets when the server restarts and is
 * per server instance; it is a speed bump, not a substitute for a strong password.
 */
export function createLoginLimiter(maxFailures = 5, windowMs = 15 * 60_000, now: () => number = Date.now) {
  const failures = new Map<string, number[]>();
  const recent = (key: string) => {
    const t = now();
    const list = (failures.get(key) ?? []).filter((at) => t - at < windowMs);
    if (list.length) failures.set(key, list);
    else failures.delete(key);
    return list;
  };
  return {
    /** Seconds until another try is allowed, or 0 if allowed now. */
    blockedFor(key: string): number {
      const list = recent(key);
      if (list.length < maxFailures) return 0;
      return Math.ceil((list[0] + windowMs - now()) / 1000);
    },
    fail(key: string) {
      failures.set(key, [...recent(key), now()]);
    },
    succeed(key: string) {
      failures.delete(key);
    },
  };
}
