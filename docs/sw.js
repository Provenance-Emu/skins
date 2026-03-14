/* Provenance Skins — Service Worker v2
   Strategy:
     - HTML pages       → network-first (always fresh, fall back to cache offline)
     - catalog.json     → network-first (stale-while-revalidate fallback)
     - versioned assets → cache-first (?v= query means content-addressed)
     - everything else  → stale-while-revalidate
*/

const CACHE_NAME = "pv-skins-v2";

// Activate immediately and delete old caches
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin GET requests
  if (url.origin !== self.location.origin || req.method !== "GET") return;

  const path = url.pathname;
  const hasVersion = url.searchParams.has("v");

  // Versioned assets (?v=hash) — cache-first, never expires (content-addressed)
  if (hasVersion) {
    event.respondWith(
      caches.match(req).then(cached => cached || fetch(req).then(res => {
        if (res.ok) caches.open(CACHE_NAME).then(c => c.put(req, res.clone()));
        return res;
      }))
    );
    return;
  }

  // HTML pages — network-first, cache as offline fallback only
  if (path.endsWith(".html") || path.endsWith("/") || path === "/skins") {
    event.respondWith(
      fetch(req)
        .then(res => {
          if (res.ok) caches.open(CACHE_NAME).then(c => c.put(req, res.clone()));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // catalog.json — network-first
  if (path.endsWith("catalog.json")) {
    event.respondWith(
      fetch(req)
        .then(res => {
          if (res.ok) caches.open(CACHE_NAME).then(c => c.put(req, res.clone()));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Everything else — stale-while-revalidate
  event.respondWith(
    caches.match(req).then(cached => {
      const fresh = fetch(req).then(res => {
        if (res.ok) caches.open(CACHE_NAME).then(c => c.put(req, res.clone()));
        return res;
      });
      return cached || fresh;
    })
  );
});
