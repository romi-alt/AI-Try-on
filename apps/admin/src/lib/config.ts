export const config = {
  // The browser talks to this app's own `/api/proxy`, which signs in the request and adds the admin key on the server.
  // The key is never part of the client bundle.
  apiUrl: "/api/proxy",
  // Shown in messages only: where the proxy forwards to is the server's `API_URL`.
  productsPageSize: 20,
  statsPollMs: 5000,
  jobsPollMs: 4000,
  processingPollMs: 3000,
  listLimit: 100, // latest sessions / jobs shown (the API allows up to 500)
  maxImageBytes: 10 * 1024 * 1024,
} as const;
