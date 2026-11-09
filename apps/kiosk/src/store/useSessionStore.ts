import { create } from "zustand";
import { api } from "@/lib/api";
import { config } from "@/lib/config";
import type { Garment, Session, TryOnJob } from "@/lib/types";

export type KioskStatus =
  | "idle"
  | "ready"
  | "capturing"
  | "uploading"
  | "processing"
  | "done"
  | "error";

type CaptureFn = () => Promise<Blob>;

type SessionState = {
  status: KioskStatus;
  error: string | null;
  session: Session | null;
  garments: Garment[];
  selectedGarmentId: string | null;
  job: TryOnJob | null;
  /** Registered by the webcam component so the store can trigger a capture. */
  captureFn: CaptureFn | null;

  startSession: () => Promise<void>;
  loadGarments: () => Promise<void>;
  selectGarment: (id: string) => void;
  registerCapture: (fn: CaptureFn | null) => void;
  runTryOn: () => Promise<void>;
  backToMirror: () => void;
  reset: () => void;
};

const initial = {
  status: "idle" as KioskStatus,
  error: null,
  session: null,
  garments: [],
  selectedGarmentId: null,
  job: null,
  captureFn: null,
};

export const useSessionStore = create<SessionState>((set, get) => ({
  ...initial,

  startSession: async () => {
    try {
      const [session] = await Promise.all([api.createSession(config.kioskId), get().loadGarments()]);
      set({ session, status: "ready", error: null });
    } catch (e) {
      set({ status: "error", error: messageOf(e) });
    }
  },

  loadGarments: async () => {
    const garments = await api.listGarments();
    set({ garments, selectedGarmentId: get().selectedGarmentId ?? garments[0]?.id ?? null });
  },

  selectGarment: (id) => set({ selectedGarmentId: id }),

  registerCapture: (fn) => set({ captureFn: fn }),

  runTryOn: async () => {
    const { session, selectedGarmentId, captureFn, status } = get();
    if (!session || !selectedGarmentId || !captureFn) return;
    if (status === "capturing" || status === "uploading" || status === "processing") return;

    try {
      set({ status: "capturing", error: null, job: null });
      const frame = await captureFn();

      set({ status: "uploading" });
      const presign = await api.presignUpload(frame.type || "image/jpeg", "capture");
      await api.uploadToPresigned(presign.upload_url, frame);

      set({ status: "processing" });
      let job = await api.createTryOnJob(session.id, selectedGarmentId, presign.key);
      set({ job });

      const deadline = Date.now() + config.jobTimeoutMs;
      while (job.status === "queued" || job.status === "processing") {
        if (Date.now() > deadline) throw new Error("Rendering timed out. Please try again.");
        await sleep(config.pollIntervalMs);
        job = await api.getTryOnJob(job.id);
        set({ job });
      }

      if (job.status === "failed") throw new Error(job.error ?? "Rendering failed.");
      set({ status: "done" });
    } catch (e) {
      set({ status: "error", error: messageOf(e) });
    }
  },

  backToMirror: () => set({ status: "ready", job: null, error: null }),

  reset: () => {
    const { session } = get();
    if (session) void api.endSession(session.id).catch(() => undefined);
    set({ ...initial });
  },
}));

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : "Unexpected error";
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
