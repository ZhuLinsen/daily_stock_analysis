// DSA Service Worker — Phase 1 PWA shell cache
//
// Issue #2137 direction: cache only the static shell + offline fallback.
// NEVER cache:
//   - Auth / session-cookie API (/api/*, /auth/*, /login, /logout)
//   - Real-time quote / report / config data
//   - Any response that depends on user credentials or carries Set-Cookie
//
// Rationale: financial data is time-sensitive; caching it would silently
// break latency-sensitive decisions and could leak auth state across
// sessions. The shell-only cache is the safest Phase 1 shape and matches
// maintainer's stated contract on issue #2137 ("Service Worker 只应缓存
// 静态壳资源和离线页，不应缓存鉴权响应、报告数据、配置数据或实时行情
// 接口").

const CACHE_NAME = "dsa-shell-v1";

const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/offline.html",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
  "/favicon.ico",
  "/favicon-32.png",
];

const OFFLINE_HTML =
  '<!doctype html><html lang="zh-CN"><head>' +
  '<meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  "<title>DSA 离线</title>" +
  "<style>" +
  "body{background:#0f172a;color:#e2e8f0;font-family:system-ui,sans-serif;" +
  "display:flex;align-items:center;justify-content:center;" +
  "min-height:100vh;margin:0;padding:1rem}" +
  "main{text-align:center;max-width:32rem}" +
  "h1{font-size:1.25rem;font-weight:600;margin-bottom:0.5rem}" +
  "p{color:#94a3b8;line-height:1.6;margin-bottom:1rem}" +
  "button{background:#22d3ee;color:#0f172a;border:0;padding:0.5rem 1rem;" +
  "border-radius:8px;font-weight:600;cursor:pointer}" +
  "</style></head><body><main>" +
  "<h1>当前离线</h1>" +
  "<p>DSA 暂时无法连接到服务器。请检查网络后重试。" +
  "整个分析后端、行情数据与登录态都不会在离线期间缓存。</p>" +
  '<button onclick="location.reload()">重新连接</button>' +
  "</main></body></html>";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      // Pre-cache offline.html from a synthesized Response so subsequent
      // navigations always have a fallback even on first install.
      await cache.put(
        "/offline.html",
        new Response(OFFLINE_HTML, {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        }),
      );
      // Best-effort precache the remaining shell assets; ignore failures
      // (e.g. dev server may not have all of them at install time).
      await Promise.allSettled(SHELL_ASSETS.map((url) => cache.add(url)));
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only handle GET; never intercept POST/PUT/DELETE (auth mutations, form submits)
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Cross-origin requests (CDN, third-party) — let the browser handle
  if (url.origin !== self.location.origin) return;
  // NEVER cache auth / API / data endpoints — always go to network
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/auth/") ||
    url.pathname === "/login" ||
    url.pathname === "/logout"
  ) {
    return;
  }
  // Navigations: network-first with shell + offline fallback
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch (err) {
          const cached = await caches.match(req);
          if (cached) return cached;
          const shell = await caches.match("/index.html");
          if (shell) return shell;
          const offline = await caches.match("/offline.html");
          if (offline) return offline;
          return new Response(OFFLINE_HTML, {
            headers: { "Content-Type": "text/html; charset=utf-8" },
          });
        }
      })(),
    );
    return;
  }
  // Other same-origin static GETs: stale-while-revalidate
  event.respondWith(
    (async () => {
      const cached = await caches.match(req);
      const network = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === "basic") {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })(),
  );
});
