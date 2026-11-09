"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SessionProvider, signOut, useSession } from "next-auth/react";

const nav = [
  { href: "/", label: "Overview" },
  { href: "/products", label: "Products" },
  { href: "/products/import", label: "Import CSV" },
  { href: "/analytics", label: "Analytics" },
  { href: "/orders", label: "Orders" },
  { href: "/sessions", label: "Sessions" },
  { href: "/jobs", label: "Try-on jobs" },
];

function Who() {
  const { data } = useSession();
  return (
    <div className="mt-8 border-t border-neutral-200 pt-4 text-xs text-neutral-500">
      <p className="truncate" title={data?.user?.email ?? ""}>
        {data?.user?.email}
      </p>
      <button type="button" onClick={() => void signOut({ callbackUrl: "/login" })} className="mt-2 rounded-md border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-100">
        Sign out
      </button>
    </div>
  );
}

/** The sidebar and page frame. The sign-in page gets none of it. */
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (path === "/login") return <>{children}</>;
  return (
    <SessionProvider>
      <div className="flex min-h-screen">
        <aside className="w-56 flex-none border-r border-neutral-200 bg-white p-5">
          <p className="mb-6 text-sm font-semibold tracking-wide text-neutral-500">ELEVARIQ ADMIN</p>
          <nav className="flex flex-col gap-1">
            {nav.map((n) => {
              const active = n.href === "/" ? path === "/" : path === n.href || (path.startsWith(`${n.href}/`) && !nav.some((o) => o.href !== n.href && o.href.startsWith(`${n.href}/`) && path.startsWith(o.href)));
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} className={`rounded-md px-3 py-2 text-sm hover:bg-neutral-100 ${active ? "bg-neutral-100 font-medium text-neutral-900" : "text-neutral-700"}`}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <Who />
        </aside>
        <main className="min-w-0 flex-1 p-8">{children}</main>
      </div>
    </SessionProvider>
  );
}
