import { hashPassword, verifyPassword } from "./password";

/**
 * Who may sign in: `ADMIN_USERS="alice@shop.pk=scrypt:...,bob@shop.pk=scrypt:..."` (email, `=`, password hash; entries
 * separated by commas). Make a hash with `npm run hash-password -w @tryon/admin`.
 */
export type AdminUsers = Map<string, string>;

export function parseAdminUsers(raw: string | undefined): AdminUsers {
  const users: AdminUsers = new Map();
  for (const entry of (raw ?? "").split(",")) {
    const at = entry.indexOf("=");
    if (at < 1) continue;
    const email = normalizeEmail(entry.slice(0, at));
    const hash = entry.slice(at + 1).trim();
    if (email && hash) users.set(email, hash);
  }
  return users;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

// Checked when the email is unknown, so an unknown email and a wrong password take the same time.
const DUMMY_HASH = hashPassword("not-a-real-password");

/** The signed-in user's email, or null. Never says whether it was the email or the password that was wrong. */
export function authenticate(users: AdminUsers, email: string, password: string): string | null {
  const key = normalizeEmail(email);
  const stored = users.get(key);
  const ok = verifyPassword(password, stored ?? DUMMY_HASH);
  return stored && ok ? key : null;
}
