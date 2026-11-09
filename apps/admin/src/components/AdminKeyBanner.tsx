"use client";

import { config } from "@/lib/config";
import { Banner } from "./Banner";

/** Without a key every admin request is refused, so say so up front rather than failing page by page. */
export function AdminKeyBanner() {
  if (config.adminKey) return null;
  return (
    <Banner kind="warning">
      No admin key is configured. Set <code>NEXT_PUBLIC_ADMIN_API_KEY</code> (it must match <code>ADMIN_API_KEY</code> on the
      API) and rebuild this app.
    </Banner>
  );
}
