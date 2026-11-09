type Props = { page: number; pages: number; total: number; pageSize: number; onPage: (page: number) => void };

export function Pagination({ page, pages, total, pageSize, onPage }: Props) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const btn = "rounded-md border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-neutral-600">
      <span>
        {from}-{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span className="tabular-nums">
          Page {page} of {Math.max(pages, 1)}
        </span>
        <button type="button" className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}
