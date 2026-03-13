/* Provenance Skins — Service Worker
   Cache name: pv-skins-v1
   Strategy:
     - catalog.json → network-first (stale-while-revalidate fallback)
     - static assets (HTML, CSS, JS) → cache-first
*/

const CACHE_NAME = "pv-skins-v1";
const STATIC_ASSETS = [
  "./",
  "./index.html",
  "./style.css",
  "./js/browse.js",
  "./catalog.json",
];

// Install: pre-cache static assets
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: delete old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: network-first for catalog.json, cache-first for everything else
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  if (url.pathname.endsWith("catalog.json")) {
    // Network-first for catalog (fresh data preferred)
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    // Cache-first for static assets
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        });
      })
    );
  }
});
