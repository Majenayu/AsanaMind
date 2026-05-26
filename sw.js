/*
 * Sunday · AsanaMind — Service Worker (item 36)
 *
 * Caches all static assets so the app works fully offline after first load.
 * Strategy: cache-first for static assets, network-first for API calls.
 */
// Bumped to v6 — added Web Push notification handler (item 11) and the
// privacy + verify routes need to bypass the offline cache (always live).
const CACHE_NAME = 'sunday-v6';
const STATIC_ASSETS = [
    '/',
    '/home',
    '/profile',
    '/static/poses.js',
    '/static/voice-kb.js',
    '/static/pose-cues.js',
    '/static/practice-flow.js',
    '/static/pose-notes.js',
    '/static/courses.js',
    '/manifest.json',
    '/assets/logo.png',
    '/assets/poses/tadasana.jpg',
    '/assets/poses/urdhva.png',
    '/assets/poses/anjali.png',
    '/assets/poses/vrikshasana.png',
    '/assets/poses/uttanasana.png',
    '/assets/poses/sukhasana.png',
    '/assets/poses/dandasana.png',
    '/assets/poses/baddha.png',
    '/assets/poses/paschimottanasana.png',
    '/assets/poses/balasana.png',
    '/assets/poses/adhomukha.png',
    '/assets/poses/warrior1.png',
    '/assets/poses/warrior2.png',
    '/assets/poses/trikonasana.png',
    '/assets/poses/utkatasana.png',
    '/assets/poses/parsvakonasana.png',
    '/assets/poses/setubandhasana.png',
    '/assets/poses/warrior3.png',
    '/assets/poses/ardhachandra.png',
    '/assets/poses/natarajasana.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Always live — verification + privacy + push must hit the server.
    if (url.pathname.startsWith('/verify/') || url.pathname === '/privacy') {
        event.respondWith(fetch(event.request));
        return;
    }

    // API calls: network-first, fallback to cache.
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
        return;
    }

    // HTML pages (/, /home, /profile): network-first so deploys land
    // immediately without waiting for SW update.
    if (event.request.mode === 'navigate' || event.request.headers.get('accept')?.includes('text/html')) {
        event.respondWith(
            fetch(event.request).then(response => {
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => caches.match(event.request))
        );
        return;
    }

    // Static assets (JS, CSS, images): cache-first, fallback to network.
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                if (response.ok && event.request.method === 'GET') {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            });
        })
    );
});

// ─────────────────────────────────────────────────
// WEB PUSH (item 11) — daily reminder notifications
// ─────────────────────────────────────────────────
self.addEventListener('push', (event) => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch (_) { data = { title: 'Sunday', body: event.data?.text() || '' }; }
    const title = data.title || 'Sunday is waiting';
    const body = data.body || 'A few minutes of practice today goes a long way.';
    const tag = data.tag || 'sunday-reminder';
    const url = data.url || '/home';

    event.waitUntil(self.registration.showNotification(title, {
        body,
        tag,
        icon: '/assets/logo.png',
        badge: '/assets/logo.png',
        vibrate: [120, 60, 120],
        data: { url },
        actions: [
            { action: 'open', title: 'Open Sunday' },
            { action: 'dismiss', title: 'Later' },
        ],
    }));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    if (event.action === 'dismiss') return;
    const url = event.notification.data?.url || '/home';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
            for (const c of list) {
                if (c.url.includes(url) && 'focus' in c) return c.focus();
            }
            return self.clients.openWindow(url);
        })
    );
});
