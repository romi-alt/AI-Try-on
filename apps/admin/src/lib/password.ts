import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

/**
 * Password hashes for the admin allow-list: `scrypt:<salt hex>:<hash hex>`. scrypt is in Node's standard library, so
 * there is no extra dependency, and it is slow on purpose.
 */
const KEY_LENGTH = 64;

export function hashPassword(password: string, salt: Buffer = randomBytes(16)): string {
  return `scrypt:${salt.toString("hex")}:${scryptSync(password, salt, KEY_LENGTH).toString("hex")}`;
}

/** True if `password` matches `stored`. A malformed `stored` never matches (and never throws). */
export function verifyPassword(password: string, stored: string): boolean {
  const [scheme, saltHex, hashHex] = stored.split(":");
  if (scheme !== "scrypt" || !saltHex || !hashHex || !/^[0-9a-f]+$/i.test(saltHex + hashHex) || hashHex.length !== KEY_LENGTH * 2) {
    return false;
  }
  const expected = Buffer.from(hashHex, "hex");
  const actual = scryptSync(password, Buffer.from(saltHex, "hex"), KEY_LENGTH);
  return timingSafeEqual(actual, expected);
}
