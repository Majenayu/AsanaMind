/*
 * Sunday · AsanMinds — offline write queue.
 *
 * Tiny IndexedDB-backed outbox. The page calls OfflineQueue.apiWrite()
 * instead of fetch() for any state-changing request. If the network is
 * up, it goes straight through; if not, we persist the request and
 * register a Background Sync tag (`flush-outbox`) so the service worker
 * replays it the moment connectivity returns. Safari, which still does
 * not implement Background Sync, gets a manual nudge: every time the
 * `online` event fires we postMessage the SW to flush.
 *
 * Schema:
 *     DB:    asan-outbox  (v1)
 *     Store: queue        (keyPath: 'id', autoIncrement)
 *     Item:  { id, url, method, body, headers, createdAt, attempts, idempotencyKey }
 *
 * Public API (window.OfflineQueue):
 *     apiWrite(url, body, opts) -> Promise<Response>
 *     enqueue(url, body, opts)  -> Promise<id>     // force-queue
 *     pending()                  -> Promise<number>
 *     flush()                    -> Promise<void>  // manual nudge
 *     onChange(cb)               -> unsubscribe fn
 */
(function () {
    'use strict';

    const DB_NAME = 'asan-outbox';
    const STORE = 'queue';
    const TAG = 'flush-outbox';

    // ── IndexedDB helpers ─────────────────────────────────────
    function open() {
        return new Promise((resolve, reject) => {
            const r = indexedDB.open(DB_NAME, 1);
            r.onupgradeneeded = () => {
                r.result.createObjectStore(STORE, {
                    keyPath: 'id', autoIncrement: true,
                });
            };
            r.onsuccess = () => resolve(r.result);
            r.onerror = () => reject(r.error);
        });
    }

    async function tx(mode, fn) {
        const db = await open();
        return new Promise((resolve, reject) => {
            const t = db.transaction(STORE, mode);
            const store = t.objectStore(STORE);
            let result;
            Promise.resolve(fn(store)).then((v) => { result = v; });
            t.oncomplete = () => resolve(result);
            t.onerror = () => reject(t.error);
        });
    }

    // ── Listener bus ──────────────────────────────────────────
    const listeners = new Set();
    function notify() {
        listeners.forEach((cb) => { try { cb(); } catch (_) { } });
    }

    // ── Core ──────────────────────────────────────────────────
    async function enqueue(url, body, opts) {
        opts = opts || {};
        const item = {
            url,
            method: (opts.method || 'POST').toUpperCase(),
            body: body || null,
            headers: opts.headers || {},
            createdAt: Date.now(),
            attempts: 0,
            idempotencyKey: opts.idempotencyKey || cryptoRandomId(),
        };
        const id = await tx('readwrite', (store) => {
            return new Promise((resolve, reject) => {
                const r = store.add(item);
                r.onsuccess = () => resolve(r.result);
                r.onerror = () => reject(r.error);
            });
        });
        notify();
        // Try to register Background Sync; ignore silently if unsupported.
        if ('serviceWorker' in navigator && 'SyncManager' in window) {
            try {
                const reg = await navigator.serviceWorker.ready;
                await reg.sync.register(TAG);
            } catch (_) { /* best-effort */ }
        }
        return id;
    }

    async function pending() {
        return tx('readonly', (store) => {
            return new Promise((resolve) => {
                const r = store.count();
                r.onsuccess = () => resolve(r.result || 0);
                r.onerror = () => resolve(0);
            });
        });
    }

    /**
     * Try a write; on network failure, queue it.
     * Returns a Response — when queued, returns a synthetic
     * { ok: true, queued: true } response so callers don't have to
     * special-case the offline path. Their UI optimistically updates
     * either way, since the queued item will sync.
     */
    async function apiWrite(url, body, opts) {
        opts = opts || {};
        const method = (opts.method || 'POST').toUpperCase();
        const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
        const init = {
            method,
            headers,
            credentials: 'same-origin',
            body: body == null ? undefined : JSON.stringify(body),
        };

        // If we know we're offline, skip the network attempt entirely.
        if (navigator && navigator.onLine === false) {
            await enqueue(url, body, opts);
            return syntheticResponse({ queued: true, ok: true, offline: true });
        }

        try {
            const resp = await fetch(url, init);
            // Treat 5xx and 408 as transient — queue for retry.
            if (resp.status >= 500 || resp.status === 408) {
                await enqueue(url, body, opts);
                return syntheticResponse({ queued: true, ok: true, transient: true, status: resp.status });
            }
            return resp;
        } catch (err) {
            // Network failed — queue it.
            await enqueue(url, body, opts);
            return syntheticResponse({ queued: true, ok: true, offline: true });
        }
    }

    function syntheticResponse(payload) {
        return new Response(JSON.stringify(payload), {
            status: 202,
            headers: { 'Content-Type': 'application/json', 'X-OfflineQueue': 'queued' },
        });
    }

    function cryptoRandomId() {
        try {
            const b = new Uint8Array(8);
            crypto.getRandomValues(b);
            return Array.from(b).map((x) => x.toString(16).padStart(2, '0')).join('');
        } catch (_) {
            return String(Date.now()) + Math.random().toString(16).slice(2, 10);
        }
    }

    async function flush() {
        // Ask the SW to drain. Even on browsers without Background Sync,
        // a postMessage works because the SW listens for 'flush-outbox'.
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage({ type: 'flush-outbox' });
        }
    }

    function onChange(cb) {
        listeners.add(cb);
        return () => listeners.delete(cb);
    }

    // SW notifies us back when a flush completes — refresh listeners.
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.addEventListener('message', (event) => {
            const d = event.data || {};
            if (d.type === 'outbox-flushed') notify();
        });
    }

    // Auto-flush on `online` event so Safari (no Background Sync) catches up.
    window.addEventListener('online', () => { flush(); notify(); });
    window.addEventListener('offline', () => { notify(); });

    window.OfflineQueue = { apiWrite, enqueue, pending, flush, onChange };
})();
