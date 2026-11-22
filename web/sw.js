// Chisel service worker: makes the app installable and quick to open.
// App files: network first (so updates arrive), cached copy if offline.
// /api/* is never cached or touched — messages and keys always go to the server live.
const CACHE = "chisel-app-v5";
const SHELL = [
  "./", "index.html", "manifest.webmanifest", "favicon.ico", "css/app.css",
  "js/app.js", "js/api.js", "js/chisel.js", "js/config.js", "js/data.js", "js/notify.js", "js/png.js", "js/store.js", "js/ui.js",
  "vendor/libs.js", "js/compat.js", "fonts/arimo-latin-400-normal.woff2", "fonts/arimo-latin-700-normal.woff2",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/chisel-wordmark-header.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("index.html")))
  );
});
