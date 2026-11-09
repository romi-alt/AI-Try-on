/**
 * Lets the API client tell the connectivity monitor "a request just failed to reach the server" without the two
 * knowing about each other (the monitor depends on the API URL, the client on nothing).
 */
let nudge: (() => void) | null = null;

export const connectivityBus = {
  /** The monitor registers itself here while it runs. */
  register(fn: (() => void) | null) {
    nudge = fn;
  },
  /** Called by the API client when a request could not reach the server (no HTTP answer at all). */
  reportNetworkFailure() {
    nudge?.();
  },
};
