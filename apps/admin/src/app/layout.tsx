import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Try-On Admin",
  description: "Catalog and session management for the AI try-on mirror",
};

const nav = [
  { href: "/", label: "Overview" },
  { href: "/garments", label: "Garments" },
  { href: "/sessions", label: "Sessions" },
  { href: "/jobs", label: "Jobs" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <div className="flex min-h-screen">
          <aside className="w-56 border-r border-neutral-200 bg-white p-5">
            <p className="mb-6 text-sm font-semibold tracking-wide text-neutral-500">TRY-ON ADMIN</p>
            <nav className="flex flex-col gap-1">
              {nav.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="rounded-md px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-100"
                >
                  {n.label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
