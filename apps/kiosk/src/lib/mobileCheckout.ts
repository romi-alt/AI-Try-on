import { ApiError } from "./api";

/**
 * The idempotency-key policy for paying on the phone.
 *
 * One key per payment attempt. When the outcome is unknown (the connection dropped, the server timed out, a 5xx)
 * the same key is reused on the retry, so the server returns the order it already placed instead of charging
 * twice. When the server gave a definite answer (a 4xx: declined, out of stock, cart empty) that attempt is over,
 * and the next tap is a fresh one with a new key.
 */
export function createCheckoutAttempts(newKey: () => string = () => crypto.randomUUID()) {
  let key: string | null = null;
  return {
    /** The key to send for this tap. */
    current(): string {
      return (key ??= newKey());
    },
    /** Call with the failure from a checkout request; drops the key when the outcome is definite. */
    failed(error: unknown): void {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) key = null;
    },
    /** Call after success, or when the cart on screen changed. */
    reset(): void {
      key = null;
    },
  };
}
