// ============================================================
// CLOW Service Worker v9 — self-healing
// - Bump de versao forca clientes antigos (v8, v7...) a atualizar
// - Ativa imediatamente + claim de todos os clients abertos
// - Nuca TODOS os caches antigos na ativacao (nao so os diferentes)
// - Listener pra cleanup manual via postMessage({type:'NUKE'})
// - Bypass total de qualquer path do Chatwoot/CRM
// ============================================================

const CACHE_NAME = 'system-clow-v10-support';
const urlsToCache = [
  '/static/icon.svg',
  '/static/manifest.json'
];

// Install: nunca fica esperando, skipWaiting imediato
self.addEventListener('install', event => {
  event.waitUntil(
    (async () => {
      try {
        const cache = await caches.open(CACHE_NAME);
        await cache.addAll(urlsToCache);
      } catch (e) {
        // Nao bloqueia install se falhar pre-cache
      }
      await self.skipWaiting();
    })()
  );
});

// Activate: deleta TODOS os caches de versoes anteriores + claim all clients
self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.map(n => (n !== CACHE_NAME ? caches.delete(n) : Promise.resolve()))
      );
      await self.clients.claim();
      // Informa todos os clients que o SW mudou — pra eles reload se quiserem
      const clis = await self.clients.matchAll({ includeUncontrolled: true });
      clis.forEach(c => { try { c.postMessage({ type: 'SW_UPDATED', version: CACHE_NAME }); } catch (e) {} });
    })()
  );
});

// Paths do Chatwoot/CRM que NUNCA devem ser cacheados/interceptados
const BYPASS = /^\/(cw|crm-direct|cable|vite|packs|assets|brand-assets|auth|api|enterprise|rails|widget|hook|reset-cache|app\/(login|accounts|reset|signup|confirm|setup))\b|^\/(apple-icon|favicon|android-icon|ms-icon)-|^\/manifest\.json$/;

// Fetch: network-only pra Chatwoot, network-first pro resto
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Bypass total pra paths do CRM — deixa o browser fazer fetch direto
  if (url.origin === self.location.origin && BYPASS.test(url.pathname)) {
    return;
  }
  // Non-GET: passa direto
  if (event.request.method !== 'GET') return;

  event.respondWith(
    (async () => {
      try {
        const net = await fetch(event.request);
        // So cacheia respostas OK mesmo
        if (net && net.status === 200 && net.type === 'basic') {
          const cache = await caches.open(CACHE_NAME);
          cache.put(event.request, net.clone()).catch(() => {});
        }
        return net;
      } catch (err) {
        // Network falhou: fallback pro cache. Se nao tem cache, deixa o browser mostrar erro nativo.
        const hit = await caches.match(event.request);
        if (hit) return hit;
        // Re-throw pra browser mostrar a pagina de erro de rede normal (nao response sintetica)
        throw err;
      }
    })()
  );
});

// Listener pra NUKE manual: pagina pode mandar postMessage pro SW se suicidar
self.addEventListener('message', event => {
  if (!event.data) return;
  if (event.data.type === 'NUKE') {
    event.waitUntil(
      (async () => {
        // Deleta TODOS os caches
        const names = await caches.keys();
        await Promise.all(names.map(n => caches.delete(n)));
        // Unregister self
        try { await self.registration.unregister(); } catch (e) {}
        // Avisa o cliente que pode recarregar
        const clis = await self.clients.matchAll({ includeUncontrolled: true });
        clis.forEach(c => { try { c.postMessage({ type: 'NUKE_DONE' }); } catch (e) {} });
      })()
    );
  }
});
