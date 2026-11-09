import { create } from "zustand";
import type { Connectivity } from "@/lib/connectivity";

type ConnectivityStore = { state: Connectivity; set: (state: Connectivity) => void };

/** Whether the mirror can reach its server right now. Updated only by the connectivity monitor. */
export const useConnectivityStore = create<ConnectivityStore>((set) => ({ state: "online", set: (state) => set({ state }) }));
