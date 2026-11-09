import type { Product, ProcessingStatus } from "./types";

export const PROCESSING_LABEL: Record<ProcessingStatus, string> = {
  idle: "Not processed",
  queued: "Queued",
  processing: "Processing…",
  done: "Cutout ready",
  failed: "Failed",
};

export const PROCESSING_STYLE: Record<ProcessingStatus, string> = {
  idle: "bg-neutral-100 text-neutral-600",
  queued: "bg-amber-100 text-amber-800",
  processing: "bg-blue-100 text-blue-800",
  done: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
};

/** A product whose image is still being worked on: the list keeps refreshing until none are. */
export const isBusy = (p: Pick<Product, "processing_status">) => p.processing_status === "queued" || p.processing_status === "processing";
