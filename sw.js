/*
 * Sunday · AsanMinds — Service Worker (offline-first, v12)
 *
 * Three jobs:
 *   1. Cache the full static bundle so the app shell + AR coach work
 *      offline. That now includes the vendored TF.js + MoveNet weights
 *      (~13 MB) so AR pose practice doesn't need the network.
 *   2. Network-first for HTML pages and API GETs, cache-first for
 *      static assets, never cache writes (Cache API only supports GET).
 *   3. Drain the IndexedDB outbox when Background Sync fires, so any
 *      writes made while offline get replayed when connectivity
 *      returns. The page can also nudge us with a `flush-outbox`
 *      postMessage when the browser fires its `online` event.
 */
const CACHE_NAME = 'sunday-v14';

// Tier 1 — must succeed at install or the offline experience is broken.
// We allow the install to proceed even if any of these fail individually,
// but log a warning, because the alternative (a one-shot addAll that
// rolls back on any 404) is too brittle for the 13 MB model bundle.
//
// NOTE: /home is intentionally NOT prewarmed here — the install fetch
// has no session cookie so the route 302-redirects to /. We instead
// cache /home in the runtime fetch handler on the first authenticated
// successful response.
const ESSENTIAL_ASSETS = [
    '/',
    '/static/poses.js',
    '/static/voice-kb.js',
    '/static/pose-cues.js',
    '/static/practice-flow.js',
    '/static/pose-notes.js',
    '/static/courses.js',
    '/static/offline-queue.js',
    '/static/vendor/tf.min.js',
    '/static/vendor/pose-detection.min.js',
    '/static/models/movenet/model.json',
    '/static/models/movenet/group1-shard1of3.bin',
    '/static/models/movenet/group1-shard2of3.bin',
    '/static/models/movenet/group1-shard3of3.bin',
    '/manifest.json',
    '/assets/brand/logo1.png',
    '/assets/brand/logo-192.png',
    '/assets/brand/logo-512.png',
    '/assets/brand/logo-192-maskable.png',
    '/assets/brand/logo-512-maskable.png',
    '/assets/brand/apple-touch-icon.png',
    '/assets/brand/logo.svg',
    '/assets/brand/favicon.svg',
];

// Tier 2 — nice-to-have. If a pose image fails to precache it'll be
// fetched on demand the next time it's used.
const POSE_IMAGES = [
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
    '/profile',
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE_NAME);

        // Tier 1: do not let one failure roll back the whole install.
        await Promise.all(ESSENTIAL_ASSETS.map(async (url) => {
            try {
                const resp = await fetch(url, { cache: 'reload' });
                if (resp.ok) {
                    await cache.put(url, resp.clone());
                } else {
                    console.warn('[SW install] tier-1 non-OK', url, resp.status);
                }
            } catch (e) {
                console.warn('[SW install] tier-1 fetch failed', url, e.message);
            }
        }));

        // Tier 2: best-effort, fire-and-forget.
        Promise.all(POSE_IMAGES.map((url) => fetch(url).then((r) => {
            if (r.ok) cache.put(url, r.clone()).catch(() => {});
        }).catch(() => {})));
    })());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(
            keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
        );
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    const url = new URL(req.url);

    // Cross-origin requests (CDN fallback, Google fonts, etc.) — pass through.
    if (url.origin !== self.location.origin) return;

    // Always live — verification + privacy + push must hit the server.
    if (url.pathname.startsWith('/verify/') || url.pathname === '/privacy') {
        event.respondWith(fetch(req));
        return;
    }

    // Writes never go through the cache. Pass through unmodified;
    // the page's apiWrite() helper handles offline queueing for us.
    if (req.method !== 'GET') return;

    // API calls: network-first, fallback to cache (read-only data only,
    // since writes already bailed above).
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(req).then((resp) => {
                if (resp.ok) {
                    caches.open(CACHE_NAME).then((c) =>
                        c.put(req, resp.clone()).catch(() => {})
                    );
                }
                return resp;
            }).catch(() => caches.match(req).then((cached) => {
                if (cached) return cached;
                // Synthesise a sentinel "you're offline" JSON response so
                // the page knows to fall back to local data instead of
                // showing a broken state.
                return new Response(
                    JSON.stringify({ offline: true, error: 'offline' }),
                    { status: 503, headers: { 'Content-Type': 'application/json' } }
                );
            }))
        );
        return;
    }

    // HTML pages (/, /home, /profile): network-first so fresh deploys
    // land immediately when the user is online; offline serves cache.
    const accept = req.headers.get('accept') || '';
    if (req.mode === 'navigate' || accept.includes('text/html')) {
        event.respondWith(
            fetch(req).then((resp) => {
                if (resp.ok) {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then((c) => c.put(req, clone).catch(() => {}));
                }
                return resp;
            }).catch(async () => {
                const cached = await caches.match(req);
                if (cached) return cached;
                // Last-ditch fallback: serve the home shell.
                return caches.match('/home') || caches.match('/');
            })
        );
        return;
    }

    // Static assets: cache-first, fall back to network.
    event.respondWith(
        caches.match(req).then((cached) => {
            if (cached) return cached;
            return fetch(req).then((resp) => {
                if (resp.ok) {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then((c) => c.put(req, clone).catch(() => {}));
                }
                return resp;
            }).catch(() => {
                // For poses/images we'd rather show a placeholder than 0.
                if (url.pathname.startsWith('/assets/poses/')) {
                    return caches.match('/assets/brand/logo1.png');
                }
                return new Response('', { status: 504 });
            });
        })
    );
});

// ─────────────────────────────────────────────────
// OUTBOX SYNC — replay queued writes when network returns
// ─────────────────────────────────────────────────
//
// The page-side helper at /static/offline-queue.js stores write
// attempts in IndexedDB ('asan-outbox' DB, 'queue' store) when fetch
// fails. We drain that store here whenever:
//   * the browser fires a Background Sync event with tag 'flush-outbox'
//   * the page postMessages us {type:'flush-outbox'} (fallback for
//     browsers without Background Sync, e.g., Safari)
// ─────────────────────────────────────────────────

const OUTBOX_DB = 'asan-outbox';
const OUTBOX_STORE = 'queue';

function openOutbox() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(OUTBOX_DB, 1);
        req.onupgradeneeded = () => {
            req.result.createObjectStore(OUTBOX_STORE, {
                keyPath: 'id', autoIncrement: true,
            });
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function readAllOutbox() {
    const db = await openOutbox();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(OUTBOX_STORE, 'readonly');
        const store = tx.objectStore(OUTBOX_STORE);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
    });
}

async function deleteOutboxItem(id) {
    const db = await openOutbox();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(OUTBOX_STORE, 'readwrite');
        tx.objectStore(OUTBOX_STORE).delete(id);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
    });
}

async function bumpAttempts(id) {
    const db = await openOutbox();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(OUTBOX_STORE, 'readwrite');
        const store = tx.objectStore(OUTBOX_STORE);
        const get = store.get(id);
        get.onsuccess = () => {
            const item = get.result;
            if (!item) return resolve();
            item.attempts = (item.attempts || 0) + 1;
            item.lastAttempt = Date.now();
            store.put(item);
        };
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
    });
}

async function flushOutbox() {
    let items;
    try { items = await readAllOutbox(); }
    catch (e) { console.warn('[SW] outbox open failed', e); return; }

    if (!items.length) return;
    console.log(`[SW] flushing ${items.length} queued write(s)`);

    let synced = 0;
    let failed = 0;

    for (const item of items) {
        // Cap retries — don't drain a user's battery on a permanently
        // broken request (e.g., 401 after sign-out).
        if ((item.attempts || 0) >= 8) {
            console.warn('[SW] outbox abandoning after 8 attempts', item);
            await deleteOutboxItem(item.id);
            failed++;
            continue;
        }
        try {
            const resp = await fetch(item.url, {
                method: item.method || 'POST',
                headers: { 'Content-Type': 'application/json', ...(item.headers || {}) },
                credentials: 'same-origin',
                body: item.body ? JSON.stringify(item.body) : undefined,
            });
            if (resp.ok || resp.status === 409 /* idempotent dup */) {
                await deleteOutboxItem(item.id);
                synced++;
            } else if (resp.status >= 400 && resp.status < 500 && resp.status !== 408) {
                // Permanent client error — abandon, don't retry forever.
                console.warn('[SW] outbox abandoning 4xx', item.url, resp.status);
                await deleteOutboxItem(item.id);
                failed++;
            } else {
                await bumpAttempts(item.id);
                failed++;
            }
        } catch (e) {
            await bumpAttempts(item.id);
            failed++;
        }
    }

    // Tell every open page how the flush went.
    const clients = await self.clients.matchAll({ type: 'window' });
    for (const c of clients) {
        c.postMessage({ type: 'outbox-flushed', synced, failed });
    }
}

self.addEventListener('sync', (event) => {
    if (event.tag === 'flush-outbox') {
        event.waitUntil(flushOutbox());
    }
});

self.addEventListener('message', (event) => {
    const data = event.data || {};
    if (data.type === 'flush-outbox') event.waitUntil(flushOutbox());
    if (data.type === 'skip-waiting') self.skipWaiting();
});

// ─────────────────────────────────────────────────
// WEB PUSH — daily reminder notifications
// ─────────────────────────────────────────────────
self.addEventListener('push', (event) => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; }
    catch (_) { data = { title: 'Sunday', body: event.data?.text() || '' }; }
    const title = data.title || 'Sunday is waiting';
    const body = data.body || 'A few minutes of practice today goes a long way.';
    const tag = data.tag || 'sunday-reminder';
    const url = data.url || '/home';

    event.waitUntil(self.registration.showNotification(title, {
        body,
        tag,
        icon: '/assets/brand/logo-192.png',
        badge: '/assets/brand/favicon.svg',
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
        self.clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(list => {
                for (const c of list) {
                    if (c.url.includes(url) && 'focus' in c) return c.focus();
                }
                return self.clients.openWindow(url);
            })
    );
});
