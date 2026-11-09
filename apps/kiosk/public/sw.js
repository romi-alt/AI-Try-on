/*
 * Service worker for the mirror itself (the attract screen "/" and the try-on app "/try-on").
 *
 * Its only job: if the connection is down when the mirror's browser reloads (or the kiosk reboots with the shop's
 * internet out), still show the mirror's own screen, which then says "reconnecting" and recovers by itself. It
 * never touches the API or storage (other origins), never caches a photo, and passes everything else through.
 *
 *  - Pages "/" and "/try-on": network first (so a new deploy shows up at once), the last good copy when offline.
 *  - /_next/static/* and /mediapipe/*: cache first (their file names change with every build; the pose model and
 *    its WebAssembly are large and are needed offline for guidance).
 *
 * The first visit must happen online so there is something to cache.
 */
const VERSION = "v1";
const STATIC = `mirror-static-${VERSION}`;
const PAGES = `mirror-pages-${VERSION}`;
const MIRROR_PAGES = new Set(["/", "/try-on"]);

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) {
        if (key !== STATIC && key !== PAGES) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

async function networkFirst(request) {
  const cache = await caches.open(PAGES);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timer);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request)) || (await cache.match("/")) || Response.error();
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never the API, never storage
  if (request.mode === "navigate" && MIRROR_PAGES.has(url.pathname)) {
    event.respondWith(networkFirst(request));
  } else if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/mediapipe/")) {
    event.respondWith(cacheFirst(request));
  }
});
