// Service worker schematoz-bulboz: статика — из кэша, страницы — из сети с офлайн-заглушкой, API — никогда не кэшируем.
const VER = "__V__";
const STATIC = `bulboz-static-${VER}`;
const PAGES = `bulboz-pages-${VER}`;
const OFFLINE = "/offline";
const PRECACHE = [OFFLINE, "/static/pwa/icon-192.png", "/static/pwa/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(STATIC).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![STATIC, PAGES].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/kremle/") || url.pathname.startsWith("/admin") || url.pathname.startsWith("/mod")) return;

  if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/media/")) {
    // имена версионированы (?v=… / хеш) — cache-first безопасен
    e.respondWith(caches.open(STATIC).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) c.put(req, res.clone());
      return res;
    }));
    return;
  }

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(async () => (await caches.match(req)) || caches.match(OFFLINE)));
  }
});
