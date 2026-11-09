"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { config } from "@/lib/config";
import { createStaffFeed, type StaffFeedState } from "@/lib/staffFeed";

/** The live request list for a staff key (null: not signed in yet). */
export function useStaffFeed(key: string | null): StaffFeedState {
  const [state, setState] = useState<StaffFeedState>({ status: "connecting", requests: [] });
  useEffect(() => {
    if (!key) return;
    const feed = createStaffFeed({
      wsUrl: config.wsUrl,
      key,
      fetchList: () => api.listStaffRequests(key),
      onChange: setState,
    });
    return () => feed.close();
  }, [key]);
  return key ? state : { status: "connecting", requests: [] };
}
