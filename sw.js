/*
 * Sunday · AsanaMind — Service Worker (item 36)
 *
 * Caches all static assets so the app works fully offline after first load.
 * Strategy: cache-first for static assets, network-first for API calls.
 */
const CACHE_NAME = 'sunday-v2';
const STATIC_ASSETS = [
    '/',
    '/home',
    '/profile',
    '/static/poses.js',
    '/static/voice-kb.js',
    '/static/pose-cues.js',
    '/static/practice-flow.js',
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

    // API calls: network-first, fallback to cache.
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
        return;
    }

    // Static assets: cache-first, fallback to network.
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                // Cache successful GET responses for future offline use.
                if (response.ok && event.request.method === 'GET') {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            });
        })
    );
});
