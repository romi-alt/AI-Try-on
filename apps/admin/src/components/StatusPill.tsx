import { STATUS_STYLE } from "@/lib/jobs";
import type { JobStatus } from "@/lib/types";

export function StatusPill({ status }: { status: JobStatus }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>{status}</span>;
}
