import { getServerSession } from "next-auth";
import type { NextRequest } from "next/server";
import { authOptions } from "@/lib/auth";
import { proxyToApi } from "@/lib/proxy";

export const dynamic = "force-dynamic";

async function handle(req: NextRequest, { params }: { params: { path: string[] } }) {
  const session = await getServerSession(authOptions);
  return proxyToApi({
    signedIn: !!session?.user?.email,
    method: req.method,
    path: params.path,
    search: req.nextUrl.search,
    contentType: req.headers.get("content-type"),
    body: ["GET", "HEAD"].includes(req.method) ? null : await req.arrayBuffer(),
    apiUrl: (process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, ""),
    adminKey: process.env.ADMIN_API_KEY ?? "",
  });
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
