"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { makeQueryClient } from "@/lib/queries";

export function Providers({ children }: { children: React.ReactNode }) {
  // One client for the life of the page, created once (not on every render).
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
