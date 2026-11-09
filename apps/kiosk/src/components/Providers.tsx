"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { OfflineOverlay } from "@/components/OfflineOverlay";
import { PrivacyBadge } from "@/components/PrivacyBadge";
import { useConnectivityMonitor } from "@/hooks/useConnectivityMonitor";
import { makeQueryClient } from "@/lib/queries";

/** Pages that are the mirror itself (the shopper's own phone and the staff page are not). */
const MIRROR_PATHS = new Set(["/", "/try-on"]);

function MirrorOnly({ children }: { children: React.ReactNode }) {
  return MIRROR_PATHS.has(usePathname()) ? <>{children}</> : null;
}

function ConnectivityAndOffline() {
  useConnectivityMonitor();
  useEffect(() => {
    // Lets the mirror reload and still show its own screen when the connection is down (see public/sw.js).
    if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_OFFLINE_SW !== "false" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return <OfflineOverlay />;
}

export function Providers({ children }: { children: React.ReactNode }) {
  // One client for the life of the page, created once (not on every render).
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      {children}
      <MirrorOnly>
        <ConnectivityAndOffline />
      </MirrorOnly>
      <PrivacyBadge />
    </QueryClientProvider>
  );
}
