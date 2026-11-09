export function Banner({
  kind = "error",
  children,
  onDismiss,
}: {
  kind?: "error" | "success" | "warning";
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  const style = {
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-green-200 bg-green-50 text-green-800",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`mb-4 flex items-start justify-between gap-4 rounded-lg border px-4 py-3 text-sm ${style}`}>
      <div>{children}</div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="text-lg leading-none opacity-60 hover:opacity-100">
          ×
        </button>
      )}
    </div>
  );
}
