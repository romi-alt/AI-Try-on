export const config = {
  apiUrl: (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, ""),
  // Dev-only shared key (X-Admin-Key). It is part of the client bundle, so anyone who can load this app can read
  // it: replace it with real authentication before any public deployment.
  adminKey: process.env.NEXT_PUBLIC_ADMIN_API_KEY ?? "",

  productsPageSize: 20,
  statsPollMs: 5000,
  jobsPollMs: 4000,
  listLimit: 100, // latest sessions / jobs shown (the API allows up to 500)
  maxImageBytes: 10 * 1024 * 1024,
} as const;
