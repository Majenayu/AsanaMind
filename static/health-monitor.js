/*
 * AsanMinds — health monitor (client-side bug catcher + auto-healer)
 *
 * Responsibilities:
 *   1. Defensive wrappers      — retry transient fetch failures, recover
 *                                 from common runtime errors.
 *   2. Healing rules            — match a known-failure pattern and apply
 *                                 a pre-written recovery (camera permission,
 *                                 model load, voice fallback, quota, etc.)
 *   3. Telemetry                — when nothing recovered, send a structured
 *                                 report to /api/health/report so the admin
 *                                 panel can surface it as a real bug.
 *
 * Public API:
 *   window.HealthMonitor.report(payload)   — manually log a structured event
 *   window.HealthMonitor.fetchRetry(url)   — fetch with exponential backoff
 *   window.HealthMonitor.history()         — local recent events (debug only)
 */
(function () {
    'use strict';

    // ─────────────────────────────────────────────────────────────
    // CONFIG
    // ─────────────────────────────────────────────────────────────
    const REPORT_ENDPOINT = '/api/health/report';
    const MAX_LOCAL_HISTORY = 25;          // keep last N events for /api/health and debug
    const REPORT_DEBOUNCE_MS = 1500;       // dedupe rapid identical errors
    const FETCH_RETRY_MAX = 3;
    const FETCH_RETRY_BASE_MS = 350;
    const FETCH_RETRY_TIMEOUT_MS = 8000;   // per-attempt
    const HEAL_BANNER_DURATION_MS = 6000;

    const recentReports = new Map();        // signature → lastSentAt
    const localHistory = [];

    // ─────────────────────────────────────────────────────────────
    // UTILITIES
    // ─────────────────────────────────────────────────────────────
    function now() { return Date.now(); }

    function safeStringify(obj) {
        try { return JSON.stringify(obj); } catch (_) { return '[unserializable]'; }
    }

    function buildSignature(payload) {
        // Dedupe by (type, top frame, view). We drop line/col numbers so
        // minified vs unminified errors collapse. Stack-frame normalisation
        // is best-effort but cheap.
        const stackTop = (payload.stack || '').split('\n').slice(0, 2).join('|')
            .replace(/:\d+:\d+/g, '').slice(0, 200);
        return `${payload.type || 'err'}::${stackTop}::${payload.view || ''}`;
    }

    function pushHistory(entry) {
        localHistory.push({ ...entry, ts: now() });
        if (localHistory.length > MAX_LOCAL_HISTORY) localHistory.shift();
    }

    function safeViewKey() {
        try { return (window.app && window.app.currentView) || ''; } catch (_) { return ''; }
    }

    function safePoseName() {
        try { return (window.app && window.app.currentPose) || ''; } catch (_) { return ''; }
    }

    function userIdLite() {
        try { return (window.__user_email || '').split('@')[0] || 'anon'; } catch (_) { return 'anon'; }
    }

    function buildVersion() {
        // The SW cache name is the only build-version signal we have client-side;
        // it lives behind the SW so we proxy it via a localStorage cache.
        return localStorage.getItem('sunday_sw_version') || 'unknown';
    }

    // ─────────────────────────────────────────────────────────────
    // TELEMETRY — POST to server, dedupe within window
    // ─────────────────────────────────────────────────────────────
    async function dispatchReport(payload) {
        const sig = buildSignature(payload);
        const last = recentReports.get(sig) || 0;
        if (now() - last < REPORT_DEBOUNCE_MS) return;   // dedupe burst
        recentReports.set(sig, now());

        try {
            // Use OfflineQueue if the user is offline so we never lose a bug.
            if (window.OfflineQueue) {
                window.OfflineQueue.apiWrite(REPORT_ENDPOINT, payload).catch(() => {});
            } else {
                fetch(REPORT_ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(payload),
                    keepalive: true,
                }).catch(() => {});
            }
        } catch (_) { /* never let telemetry kill the app */ }
    }

    function buildPayload(extra) {
        return {
            type: 'unknown',
            ...extra,
            url: location.pathname,
            view: safeViewKey(),
            pose: safePoseName(),
            user: userIdLite(),
            ua: navigator.userAgent,
            online: navigator.onLine,
            buildVersion: buildVersion(),
            timestamp: new Date().toISOString(),
        };
    }

    // ─────────────────────────────────────────────────────────────
    // HEAL BANNER — non-blocking toast for the user
    // ─────────────────────────────────────────────────────────────
    function showHealToast(text, kind) {
        kind = kind || 'info';
        const id = 'health-toast';
        const existing = document.getElementById(id);
        if (existing) existing.remove();
        const el = document.createElement('div');
        el.id = id;
        const palette = kind === 'fixed'
            ? 'background:#0F3D2E;color:#F5F2EB;'
            : kind === 'warn'
                ? 'background:#FDE9CC;color:#A16207;border:1px solid #E0A23F;'
                : 'background:#F5F2EB;color:#14120E;border:1px solid #D4CCB8;';
        el.style.cssText =
            'position:fixed;left:50%;transform:translateX(-50%);bottom:140px;z-index:200;' +
            'border-radius:9999px;padding:10px 18px;font-size:13px;font-weight:500;' +
            'box-shadow:0 8px 30px rgba(20,18,14,0.18);max-width:90vw;text-align:center;' +
            'cursor:pointer;font-family:Inter,system-ui,sans-serif;' + palette;
        el.textContent = text;
        el.onclick = () => el.remove();
        document.body.appendChild(el);
        setTimeout(() => { if (el.parentNode) el.remove(); }, HEAL_BANNER_DURATION_MS);
    }

    // ─────────────────────────────────────────────────────────────
    // HEALER — pattern → fix table
    // ─────────────────────────────────────────────────────────────
    const healers = [
        // Camera permission denied
        {
            id: 'camera-denied',
            test: (msg) => /Permission denied|NotAllowedError|getUserMedia/i.test(msg),
            heal() {
                showHealToast('Camera blocked — tap the lock icon and allow camera, then retry', 'warn');
                // Surface the recovery flow if app exposes one.
                try { window.app && window.app.showCameraPermissionGuide && window.app.showCameraPermissionGuide(); } catch (_) {}
                return 'showed-permission-guide';
            },
        },

        // Camera busy (another tab/app holds the device)
        {
            id: 'camera-busy',
            test: (msg) => /NotReadableError|Could not start video source|TrackStartError/i.test(msg),
            heal() {
                showHealToast('Camera is in use by another app. Close it and retry.', 'warn');
                return 'asked-user-to-free-camera';
            },
        },

        // MoveNet model failed to load → fall back to Lightning
        {
            id: 'movenet-load',
            test: (msg) => /Failed to load MoveNet|NetworkError when fetching model|model\.json/i.test(msg),
            async heal() {
                try {
                    if (typeof poseDetection !== 'undefined' && window.app && window.app.startARAssessment) {
                        // Trigger a one-time fallback flag the app reads next time it
                        // creates the detector.
                        sessionStorage.setItem('sunday_movenet_fallback', 'lightning');
                        showHealToast('Switched to lighter pose model · retrying', 'fixed');
                        return 'fallback-to-lightning';
                    }
                } catch (_) {}
                showHealToast('Pose model unavailable · check connection', 'warn');
                return 'movenet-load-failed';
            },
        },

        // Speech recognition unavailable (Chrome offline, no internet)
        {
            id: 'speech-unavailable',
            test: (msg) => /SpeechRecognition|webkitSpeechRecognition|no-speech|aborted/i.test(msg),
            heal() {
                try { localStorage.setItem('sunday_voice_disabled', '1'); } catch (_) {}
                try { window.app && window.app.toggleVoiceControl && window.app.currentVoiceState === 'on' && window.app.toggleVoiceControl(); } catch (_) {}
                showHealToast('Voice paused (offline or unsupported) — tap mic to retry', 'info');
                return 'disabled-voice-temporarily';
            },
        },

        // Network failure on a fetch we know about
        {
            id: 'network-fetch',
            test: (msg) => /Failed to fetch|TypeError: Failed to fetch|NetworkError when attempting to fetch/i.test(msg),
            heal() {
                if (window.OfflineQueue) window.OfflineQueue.flush();
                showHealToast('Connection blip — retrying in background', 'info');
                return 'flushed-offline-queue';
            },
        },

        // IndexedDB or localStorage quota exhausted
        {
            id: 'quota-exceeded',
            test: (msg) => /QuotaExceededError|exceeded the quota|NS_ERROR_DOM_QUOTA_REACHED/i.test(msg),
            heal() {
                try {
                    // Drop oldest non-essential keys.
                    const keep = new Set(['sunday_user_email', 'courseProgress', 'sunday_pwa_installed']);
                    const drops = [];
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        if (k && !keep.has(k) && k.startsWith('sunday_')) drops.push(k);
                    }
                    drops.slice(0, 10).forEach((k) => { try { localStorage.removeItem(k); } catch (_) {} });
                    showHealToast('Cleared cache to free space', 'fixed');
                    return 'purged-localstorage';
                } catch (_) { return 'quota-purge-failed'; }
            },
        },

        // Service worker stale (manifest mismatch)
        {
            id: 'sw-stale',
            test: (msg) => /Failed to update.*ServiceWorker|sw\.js.*404|Manifest fetch failed/i.test(msg),
            async heal() {
                try {
                    const reg = await navigator.serviceWorker.getRegistration();
                    if (reg) {
                        await reg.update();
                        showHealToast('Refreshed offline assets', 'fixed');
                        return 'sw-updated';
                    }
                } catch (_) {}
                return 'sw-update-failed';
            },
        },

        // Tone.js (audio context) failed to start without user gesture
        {
            id: 'audio-locked',
            test: (msg) => /AudioContext was not allowed|user gesture/i.test(msg),
            heal() {
                showHealToast('Tap anywhere to enable sound', 'info');
                return 'audio-pending-gesture';
            },
        },

        // Pose-detection runtime null/undefined keypoints
        {
            id: 'keypoints-undef',
            test: (msg) => /Cannot read propert(?:y|ies) of undefined \(reading 'keypoints'\)/.test(msg),
            heal() {
                // Usually transient — the next frame recovers.
                return 'transient-keypoints-undef';
            },
        },

        // /api/* returned 503 offline-sentinel
        {
            id: 'api-offline-sentinel',
            test: (msg, payload) => payload && payload.status === 503 && /offline/.test(msg),
            heal() {
                if (window.OfflineQueue) window.OfflineQueue.flush();
                return 'silenced-offline-sentinel';
            },
        },

        // 401 from /api/* mid-session — session likely expired
        {
            id: 'session-expired',
            test: (msg, payload) => payload && payload.status === 401 && /\/api\//.test(payload.url || ''),
            heal() {
                showHealToast('Sign-in expired — refreshing the page', 'warn');
                setTimeout(() => location.reload(), 2000);
                return 'reloaded-on-401';
            },
        },
    ];

    function tryHeal(message, payload) {
        const msg = String(message || '');
        for (const h of healers) {
            try {
                if (h.test(msg, payload)) {
                    const outcome = h.heal();
                    return { matched: h.id, outcome: typeof outcome === 'string' ? outcome : 'attempted' };
                }
            } catch (_) { /* a broken healer must not crash the page */ }
        }
        return null;
    }

    // ─────────────────────────────────────────────────────────────
    // PUBLIC API
    // ─────────────────────────────────────────────────────────────
    function report(extra) {
        const payload = buildPayload(extra || {});
        const healed = tryHeal(payload.message, payload);
        payload.healed = healed ? healed.matched : null;
        payload.healOutcome = healed ? healed.outcome : null;
        pushHistory(payload);
        dispatchReport(payload);
        return payload;
    }

    /**
     * fetch with exponential backoff retry. Use for non-mutating GETs.
     * For writes, always go through OfflineQueue.apiWrite which already
     * queues on failure.
     */
    async function fetchRetry(url, init, opts) {
        opts = opts || {};
        const max = opts.max || FETCH_RETRY_MAX;
        const baseDelay = opts.baseDelay || FETCH_RETRY_BASE_MS;
        const timeout = opts.timeout || FETCH_RETRY_TIMEOUT_MS;
        let lastErr;
        for (let attempt = 0; attempt < max; attempt++) {
            try {
                const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
                const timer = ctrl ? setTimeout(() => ctrl.abort(), timeout) : null;
                const r = await fetch(url, { ...(init || {}), signal: ctrl ? ctrl.signal : undefined });
                if (timer) clearTimeout(timer);
                if (r.ok || r.status < 500) return r; // 4xx don't retry
                lastErr = new Error(`HTTP ${r.status}`);
            } catch (e) {
                lastErr = e;
            }
            // backoff
            await new Promise((res) => setTimeout(res, baseDelay * Math.pow(2, attempt)));
        }
        report({
            type: 'fetch-retry-exhausted',
            url, message: String(lastErr && lastErr.message || lastErr || 'unknown'),
        });
        throw lastErr;
    }

    function history() { return localHistory.slice(); }

    // ─────────────────────────────────────────────────────────────
    // HOOK GLOBAL ERROR EVENTS
    // ─────────────────────────────────────────────────────────────
    function _onError(e) {
        const message = e.message || String(e.error || e);
        report({
            type: 'window-error',
            message,
            filename: e.filename,
            line: e.lineno, col: e.colno,
            stack: e.error && e.error.stack || '',
        });
    }
    function _onRejection(e) {
        const reason = e.reason;
        report({
            type: 'unhandled-rejection',
            message: (reason && reason.message) || String(reason || 'rejection'),
            stack: reason && reason.stack || '',
        });
    }
    window.addEventListener('error', _onError, true);
    window.addEventListener('unhandledrejection', _onRejection);

    window.HealthMonitor = { report, fetchRetry, history };
})();
