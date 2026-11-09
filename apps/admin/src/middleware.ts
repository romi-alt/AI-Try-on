import { withAuth } from "next-auth/middleware";

// Straight to our own sign-in page rather than NextAuth's generic one.
export default withAuth({ pages: { signIn: "/login" } });

// Everything needs a signed-in admin except the sign-in page and NextAuth's own routes. The API proxy checks the
// session itself so that it can answer 401 JSON instead of redirecting a fetch to the login page.
export const config = { matcher: ["/((?!login|api/auth|api/proxy|api/health|_next/static|_next/image|favicon.ico).*)"] };
