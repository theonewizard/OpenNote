// OpenNote app-shell service worker (roadmap P3-10). It caches the page and Vite's hashed
// assets so the app opens offline; it never touches /api/ or the probes, which always go
// to the network. Offline note data is P3-08 (IndexedDB), not this cache.
const CACHE = "opennote-shell-v1";
const SHELL = "/index.html";

async function cacheShell() {
  const cache = await caches.open(CACHE);
  const response = await fetch(SHELL, { cache: "no-cache" });
  if (!response.ok) return;
  const html = await response.clone().text();
  await cache.put(SHELL, response);
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
  await cache.addAll(assets);
  // Drop assets of earlier releases so the cache does not grow with every deploy.
  for (const key of await cache.keys()) {
    const { pathname } = new URL(key.url);
    if (pathname.startsWith("/assets/") && !assets.includes(pathname)) await cache.delete(key);
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(cacheShell().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== location.origin) return;

  if (request.mode === "navigate") {
    // Network first so a new release shows at once; the cached shell when offline.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) void cacheShell();
          return response;
        })
        .catch(() => caches.match(SHELL)),
    );
  } else if (url.pathname.startsWith("/assets/")) {
    // Hashed names never change content, so the cache wins; a miss is fetched and kept.
    // ignoreVary: module scripts send Origin and the servers answer with Vary headers
    // (Origin, Accept-Encoding), which would turn every precached asset into a miss.
    event.respondWith(
      caches.match(request, { ignoreVary: true }).then(
        (hit) =>
          hit ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
