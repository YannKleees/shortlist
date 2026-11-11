// Sift service worker: notifications, and the app shell when the connection is weak.
// Network first, so a new version arrives right away.
const CACHE = "shortlist-v8";
const SHELL = ["/", "/app.css", "/app.js", "/logic.js", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon.svg", "/fonts/bricolage-latin.woff2", "/fonts/plex-mono-500.woff2", "/vendor/leaflet.js", "/vendor/leaflet.css"];

self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match("/"))));
});

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: "Sift", body: e.data?.text() || "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Sift", {
    body: d.body || "", tag: d.tag, data: { url: d.url || "/" }, icon: "/icons/icon-192.png", badge: "/icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const open = list.find(c => new URL(c.url).origin === self.location.origin);
    if (open) { open.navigate(url).catch(() => {}); return open.focus(); }
    return self.clients.openWindow(url);
  }));
});
