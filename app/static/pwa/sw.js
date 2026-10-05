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

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = { body: event.data?.text() || "Я скучал в банке." }; }
  const title = data.title || "Гриб скучает 🍄";
  const options = {
    body: data.body || "Я не обижаюсь. Я просто закисаю.",
    icon: "/static/pwa/icon-192.png",
    badge: "/static/pwa/icon-192.png",
    tag: data.tag || "bulboz-reminder",
    data: { url: typeof data.url === "string" && data.url.startsWith("/") && !data.url.startsWith("//") ? data.url : "/" },
    vibrate: [80, 40, 80],
    renotify: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const requested = event.notification.data?.url || "/";
  const parsed = new URL(requested, self.location.origin);
  const target = parsed.origin === self.location.origin ? parsed.href : new URL("/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (client.url.startsWith(self.location.origin) && "focus" in client) {
        await client.navigate(target);
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  })());
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
