import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { authenticate, normalizeEmail, parseAdminUsers } from "./adminUsers";
import { createLoginLimiter } from "./loginLimiter";

const limiter = createLoginLimiter();

/** The session is a signed cookie (JWT); there is no user table. Only emails in `ADMIN_USERS` can sign in. */
export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/login" },
  secret: process.env.NEXTAUTH_SECRET,
  providers: [
    CredentialsProvider({
      name: "Email and password",
      credentials: { email: { label: "Email", type: "email" }, password: { label: "Password", type: "password" } },
      async authorize(credentials) {
        const email = normalizeEmail(credentials?.email ?? "");
        const password = credentials?.password ?? "";
        if (!email || !password) return null;
        if (limiter.blockedFor(email) > 0) throw new Error("TooManyAttempts");
        const users = parseAdminUsers(process.env.ADMIN_USERS);
        if (users.size === 0) throw new Error("NotConfigured");
        const who = authenticate(users, email, password);
        if (!who) {
          limiter.fail(email);
          return null;
        }
        limiter.succeed(email);
        return { id: who, email: who };
      },
    }),
  ],
};
