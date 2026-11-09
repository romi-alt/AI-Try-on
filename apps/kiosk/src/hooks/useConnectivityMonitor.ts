"use client";

import { onlineManager } from "@tanstack/react-query";
import { useEffect } from "react";
import { config } from "@/lib/config";
import { createConnectivityMonitor } from "@/lib/connectivity";
import { connectivityBus } from "@/lib/connectivityBus";
import { useConnectivityStore } from "@/store/useConnectivityStore";

/** Runs the connectivity monitor for the life of the page: `GET /health` on the API, and the data cache follows it. */
export function useConnectivityMonitor() {
  useEffect(() => {
    const monitor = createConnectivityMonitor({
      ping: async (signal) => {
        const res = await fetch(`${config.apiUrl}/health`, { cache: "no-store", signal });
        return res.ok;
      },
      onChange: (state) => {
        useConnectivityStore.getState().set(state);
        // Queries pause while offline and refetch what is stale the moment the connection returns.
        onlineManager.setOnline(state === "online");
      },
    });
    connectivityBus.register(() => monitor.nudge());
    monitor.start();
    return () => {
      connectivityBus.register(null);
      monitor.stop();
    };
  }, []);
}
