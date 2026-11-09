// Usage: npm run hash-password -w @tryon/admin -- 'the password'
// Prints the value to put after `email=` in ADMIN_USERS.
import { randomBytes, scryptSync } from "node:crypto";

const password = process.argv[2];
if (!password) {
  console.error("Usage: npm run hash-password -w @tryon/admin -- '<password>'");
  process.exit(1);
}
const salt = randomBytes(16);
console.log(`scrypt:${salt.toString("hex")}:${scryptSync(password, salt, 64).toString("hex")}`);
