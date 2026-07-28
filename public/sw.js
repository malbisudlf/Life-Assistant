// Service worker mínimo para Life Assistant (PWA instalable + shell offline).
// Estrategia: network-first para navegaciones y GET del mismo origen, con caída al
// caché si no hay red. Nunca cachea otras orígenes (la API vive en otro dominio) ni
// peticiones no-GET, para no interferir con el login ni con las llamadas autenticadas.
const CACHE = "la-shell-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((c) => c.add("/")));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Notificaciones push ──────────────────────────────────────────────────────
// Esto es lo que hace que el aviso llegue con la app cerrada: el service worker sigue
// vivo aunque no haya ninguna pestaña. El backend manda {titulo, cuerpo, url}.
self.addEventListener("push", (event) => {
  let datos;
  try {
    datos = event.data ? event.data.json() : {};
  } catch {
    // Cuerpo que no es JSON: se muestra tal cual en vez de tragarse el aviso.
    datos = { cuerpo: event.data ? event.data.text() : "" };
  }
  const titulo = datos.titulo || "Life Assistant";
  event.waitUntil(
    self.registration.showNotification(titulo, {
      body: datos.cuerpo || "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      // Reemplaza el aviso anterior del mismo evento en vez de apilarlos.
      tag: datos.url || titulo,
      data: { url: datos.url || "/" },
    })
  );
});

// Al tocar el aviso: reutiliza la pestaña abierta si la hay, y si no abre una.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destino = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((lista) => {
      for (const cliente of lista) {
        if ("focus" in cliente) return cliente.focus();
      }
      return self.clients.openWindow ? self.clients.openWindow(destino) : undefined;
    })
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // no tocar la API ni terceros

  event.respondWith(
    fetch(request)
      .then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(request).then((hit) => hit || caches.match("/"))
      )
  );
});
