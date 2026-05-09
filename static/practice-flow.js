/*
 * Sunday · AsanaMind — Practice Flow Module
 *
 * Adds three independent feature modules stacked on top of the existing
 * engine:
 *   TimedHold       — 30-second hold timer with spoken countdown (item 16)
 *   BreathPacing    — animated inhale/exhale circle (item 17)
 *   PoseMastery     — bronze/silver/gold tiers per pose (item 24)
 *   TransitionHint  — "next: Warrior II, from here step forward" (item 11)
 *   RuleFocus       — tracks chronic per-rule failures for calibration (item 10)
 *   SessionRecap    — post-session summary card (item 25)
 *   PoseProgress    — 30-day alignment graph per pose (item 27)
 *
 * All modules are pure UI + localStorage — no dependencies, no server.
 */
(function () {
    'use strict';

    // ─────────────────────────────────────────────────────────────
    // TimedHold — spoken countdown for any session
    // ─────────────────────────────────────────────────────────────
    const TimedHold = {
        _timer: null, _startedAt: 0, _durationS: 0, _onTick: null, _onEnd: null,
        /**
         * Start a timer that fires `onTick(remainingS)` every second and
         * `onEnd()` when it hits zero. Call stop() to cancel.
         */
        start(durationS, onTick, onEnd) {
            this.stop();
            this._durationS = durationS;
            this._startedAt = Date.now();
            this._onTick = onTick; this._onEnd = onEnd;
            const tick = () => {
                const elapsed = (Date.now() - this._startedAt) / 1000;
                const remaining = Math.max(0, Math.ceil(this._durationS - elapsed));
                if (this._onTick) this._onTick(remaining);
                if (remaining <= 0) {
                    if (this._onEnd) this._onEnd();
                    this.stop();
                    return;
                }
                this._timer = setTimeout(tick, 1000);
            };
            tick();
        },
        stop() {
            if (this._timer) { clearTimeout(this._timer); this._timer = null; }
            this._onTick = null; this._onEnd = null;
        },
        isRunning() { return !!this._timer; },
    };

    // ─────────────────────────────────────────────────────────────
    // BreathPacing — overlay circle that expands on inhale, contracts on
    // exhale. 4-4 pattern by default. Call start() / stop().
    // ─────────────────────────────────────────────────────────────
    const BreathPacing = {
        _running: false, _rafId: null, _startTs: 0,
        start(opts) {
            if (this._running) return;
            opts = opts || {};
            const inhale = opts.inhale || 4; // seconds
            const exhale = opts.exhale || 4;
            const cycle = (inhale + exhale) * 1000;
            this._running = true;
            this._startTs = Date.now();

            // Create the overlay circle.
            let el = document.getElementById('breath-circle');
            if (!el) {
                el = document.createElement('div');
                el.id = 'breath-circle';
                el.style.cssText = [
                    'position:absolute', 'right:16px', 'bottom:16px',
                    'z-index:115', 'border:3px solid rgba(224,162,63,0.8)',
                    'border-radius:999px', 'pointer-events:none',
                    'background:rgba(15,61,46,0.15)', 'backdrop-filter:blur(4px)',
                    'display:flex', 'align-items:center', 'justify-content:center',
                    'font-family:Fraunces,serif', 'color:#F5F2EB', 'font-size:16px',
                    'transition:width 0.05s linear,height 0.05s linear',
                    'text-shadow:0 1px 4px rgba(0,0,0,0.5)',
                ].join(';');
                // Attach to the video container so it stays within the AR feed.
                const vc = document.getElementById('video-container');
                if (vc) vc.appendChild(el);
                else document.body.appendChild(el);
            }

            const render = () => {
                if (!this._running) return;
                const t = ((Date.now() - this._startTs) % cycle) / 1000;
                let phase, pct;
                if (t < inhale) { phase = 'Inhale'; pct = t / inhale; }
                else { phase = 'Exhale'; pct = 1 - ((t - inhale) / exhale); }
                const minSize = 80, maxSize = 160;
                const size = Math.round(minSize + (maxSize - minSize) * pct);
                el.style.width = size + 'px';
                el.style.height = size + 'px';
                el.textContent = phase;
                this._rafId = requestAnimationFrame(render);
            };
            render();
        },
        stop() {
            this._running = false;
            if (this._rafId) cancelAnimationFrame(this._rafId);
            const el = document.getElementById('breath-circle');
            if (el) el.remove();
        },
    };

    // ─────────────────────────────────────────────────────────────
    // PoseMastery — tier per pose based on best-hold × peak alignment.
    // Consumes localStorage 'sunday_voice_history' from VoiceKB.
    // ─────────────────────────────────────────────────────────────
    const PoseMastery = {
        /** Tier for a single pose from its history records. */
        tierFor(poseName) {
            const arr = this._read();
            const own = arr.filter(r => r.pose === poseName);
            if (!own.length) return { tier: 'none', sessions: 0 };
            const best = own.reduce((m, r) => r.peakScore > m.peakScore ? r : m, own[0]);
            const longHolds = own.filter(r => r.durationS >= 20).length;
            const sessions = own.length;

            // Gold:   peak ≥ 90 AND ≥3 holds of 20 s+ AND ≥5 sessions
            // Silver: peak ≥ 80 AND ≥2 holds of 15 s+ AND ≥3 sessions
            // Bronze: peak ≥ 70 AND ≥1 session
            if (best.peakScore >= 90 && longHolds >= 3 && sessions >= 5) return { tier: 'gold', sessions, best: best.peakScore };
            if (best.peakScore >= 80 && own.filter(r => r.durationS >= 15).length >= 2 && sessions >= 3) return { tier: 'silver', sessions, best: best.peakScore };
            if (best.peakScore >= 70) return { tier: 'bronze', sessions, best: best.peakScore };
            return { tier: 'starting', sessions, best: best.peakScore };
        },
        /** Full map of pose → tier for rendering on the profile page. */
        allTiers(poseNames) {
            const out = {};
            for (const name of poseNames || []) out[name] = this.tierFor(name);
            return out;
        },
        _read() {
            try { return JSON.parse(localStorage.getItem('sunday_voice_history') || '[]'); } catch(_) { return []; }
        },
    };

    // ─────────────────────────────────────────────────────────────
    // TransitionHint — natural-language transition between two poses.
    // Keyed by destination pose; a few hand-authored hints and a safe
    // fallback.
    // ─────────────────────────────────────────────────────────────
    const TRANSITIONS = {
        'Virabhadrasana I': 'Step the back foot forward into a high lunge, front knee over ankle, sweep the arms up.',
        'Virabhadrasana II': 'Open the back foot parallel to the short edge, arms reach wide and long.',
        'Virabhadrasana III': 'Shift weight into the front foot, hinge at the hips as the back leg lifts parallel.',
        'Utthita Trikonasana': 'Straighten the front leg, hinge at the hip, reach the top arm to the sky.',
        'Utthita Parsvakonasana': 'Bend the front knee deep, reach the top arm over the ear, bottom hand finds support.',
        'Utkatasana': 'Bring the feet together, sit the hips low as if on a chair, arms reach up.',
        'Adho Mukha Svanasana': 'Plant the hands shoulder-width, walk the feet back, hips lift high.',
        'Uttanasana': 'Step the feet together, hinge from the hips, let the head hang heavy.',
        'Tadasana': 'Return to the top of the mat, feet hip-width, weight even.',
        'Vrikshasana': 'Shift weight into the standing foot, place the raised sole on the inner thigh.',
        'Balasana': 'Come to the mat, knees wide, hips to heels, forehead down.',
        'Setu Bandhasana': 'Lie on your back, feet hip-width near the sit bones, press into the feet and lift the hips.',
        'Ardha Chandrasana': 'From Triangle, bend the front knee, step the back foot in, lift the back leg as the bottom hand finds a block.',
        'Natarajasana': 'From Tadasana, bend the back knee, catch the inside of the foot, reach the front arm up.',
    };
    const TransitionHint = {
        hintFor(toPose) {
            return TRANSITIONS[toPose] || null;
        },
    };

    // ─────────────────────────────────────────────────────────────
    // RuleFocus — chronic per-rule failure tracker. Saves the rule IDs
    // that fail most often across the user's last 14 days of practice.
    // Consumed by the frame loop to cue those rules faster.
    // ─────────────────────────────────────────────────────────────
    const FOCUS_KEY = 'sunday_rule_focus';
    const RuleFocus = {
        /** Record a rule fail event. */
        bump(ruleId) {
            if (!ruleId) return;
            try {
                const raw = localStorage.getItem(FOCUS_KEY);
                const log = raw ? JSON.parse(raw) : [];
                log.push({ id: ruleId, ts: Date.now() });
                // Keep only 14 days, max 500 entries.
                const cutoff = Date.now() - 14 * 24 * 3600 * 1000;
                const pruned = log.filter(e => e.ts > cutoff).slice(-500);
                localStorage.setItem(FOCUS_KEY, JSON.stringify(pruned));
            } catch(_){}
        },
        /** Return the top N chronic-failure rule IDs. */
        topChronic(n) {
            try {
                const log = JSON.parse(localStorage.getItem(FOCUS_KEY) || '[]');
                const counts = {};
                for (const e of log) counts[e.id] = (counts[e.id] || 0) + 1;
                const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
                return entries.slice(0, n || 5).map(([id, count]) => ({ id, count }));
            } catch(_) { return []; }
        },
        /** Check if a rule is chronic (in top 3, hit ≥5 times). */
        isChronic(ruleId) {
            const top = this.topChronic(3);
            return top.some(r => r.id === ruleId && r.count >= 5);
        },
    };

    // ─────────────────────────────────────────────────────────────
    // SessionRecap — post-session summary card. Called on stop, renders
    // a 10-second recap with peak score, hold time, next-focus.
    // ─────────────────────────────────────────────────────────────
    const SessionRecap = {
        show(session) {
            if (!session || !session.pose) return;
            const existing = document.getElementById('session-recap');
            if (existing) existing.remove();

            const el = document.createElement('div');
            el.id = 'session-recap';
            el.style.cssText = [
                'position:fixed', 'inset:0', 'z-index:130',
                'background:rgba(15,19,12,0.88)', 'backdrop-filter:blur(12px)',
                'display:flex', 'align-items:center', 'justify-content:center',
                'padding:24px', 'opacity:0', 'transition:opacity 0.3s ease',
            ].join(';');

            const peak = Math.round(session.peakScore || 0);
            const durS = Math.round(session.durationS || 0);
            const feedback = peak >= 85 ? 'Beautiful form.'
                            : peak >= 70 ? 'Good practice.'
                            : peak >= 50 ? 'Solid start — keep refining.'
                                         : 'Every practice counts.';

            el.innerHTML = `
                <div style="background:#F5F2EB;border-radius:28px;max-width:480px;width:100%;padding:32px;box-shadow:0 30px 80px rgba(0,0,0,0.5);text-align:center;position:relative">
                    <button onclick="document.getElementById('session-recap').remove()" style="position:absolute;top:18px;right:18px;width:40px;height:40px;border-radius:999px;background:#EEE9DE;color:#14120E;border:0;font-size:20px;cursor:pointer">\u00d7</button>
                    <span class="kicker" style="color:#C2552F;letter-spacing:0.22em;font-size:11px">Session recap</span>
                    <div style="font-family:Fraunces,serif;font-size:28px;font-weight:400;color:#14120E;margin:6px 0 4px">${session.poseSanskrit || session.pose}</div>
                    <div style="color:#4A453B;font-size:13px;margin-bottom:24px">${feedback}</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px">
                        <div style="background:#EEE9DE;border-radius:16px;padding:16px">
                            <div class="kicker" style="color:#7A7364;font-size:10px">Peak alignment</div>
                            <div style="font-family:Fraunces,serif;font-size:36px;font-weight:300;color:#0F3D2E;line-height:1;margin-top:4px">${peak}%</div>
                        </div>
                        <div style="background:#EEE9DE;border-radius:16px;padding:16px">
                            <div class="kicker" style="color:#7A7364;font-size:10px">Held for</div>
                            <div style="font-family:Fraunces,serif;font-size:36px;font-weight:300;color:#0F3D2E;line-height:1;margin-top:4px">${durS}s</div>
                        </div>
                    </div>
                    <button onclick="document.getElementById('session-recap').remove()" style="background:#0F3D2E;color:#F5F2EB;border:0;border-radius:9999px;padding:12px 32px;font-family:inherit;font-size:14px;cursor:pointer">Done</button>
                </div>`;
            document.body.appendChild(el);
            requestAnimationFrame(() => el.style.opacity = '1');
            // Auto-dismiss after 10 s
            setTimeout(() => { if (el.parentNode) { el.style.opacity = '0'; setTimeout(() => el.remove(), 350); } }, 10000);
        },
    };

    // ─────────────────────────────────────────────────────────────
    // PoseProgress — 30-day alignment line graph per pose.
    // Pure SVG, no deps. Returns SVG string ready to inject.
    // ─────────────────────────────────────────────────────────────
    const PoseProgress = {
        svgFor(poseName, opts) {
            opts = opts || {};
            const width = opts.width || 380;
            const height = opts.height || 120;
            const arr = this._read().filter(r => r.pose === poseName);
            const now = Date.now();
            const cutoff = now - 30 * 24 * 3600 * 1000;
            const points = arr.filter(r => r.ts >= cutoff).sort((a, b) => a.ts - b.ts);
            if (points.length < 2) {
                return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><text x="${width/2}" y="${height/2}" text-anchor="middle" fill="#7A7364" font-family="Inter,sans-serif" font-size="13">Practise a few more times to see your progress</text></svg>`;
            }
            const pad = 18;
            const innerW = width - pad * 2;
            const innerH = height - pad * 2;
            const minScore = Math.max(0, Math.min(...points.map(p => p.peakScore)) - 10);
            const maxScore = 100;
            const xFor = (i) => pad + (i / (points.length - 1)) * innerW;
            const yFor = (s) => pad + innerH - ((s - minScore) / (maxScore - minScore)) * innerH;

            // Polyline path
            const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i).toFixed(1)} ${yFor(p.peakScore).toFixed(1)}`).join(' ');
            // Dots
            const dots = points.map((p, i) => `<circle cx="${xFor(i).toFixed(1)}" cy="${yFor(p.peakScore).toFixed(1)}" r="3" fill="#E0A23F"/>`).join('');

            return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
                <rect x="0" y="0" width="${width}" height="${height}" fill="#EEE9DE" rx="12"/>
                <line x1="${pad}" y1="${yFor(90).toFixed(1)}" x2="${width - pad}" y2="${yFor(90).toFixed(1)}" stroke="#C7DBCE" stroke-dasharray="3 4"/>
                <text x="${width - pad - 2}" y="${(yFor(90) - 4).toFixed(1)}" text-anchor="end" fill="#6FA089" font-family="Inter,sans-serif" font-size="10">90%</text>
                <path d="${d}" fill="none" stroke="#0F3D2E" stroke-width="2" stroke-linejoin="round"/>
                ${dots}
            </svg>`;
        },
        _read() {
            try { return JSON.parse(localStorage.getItem('sunday_voice_history') || '[]'); } catch(_) { return []; }
        },
    };

    window.PracticeFlow = { TimedHold, BreathPacing, PoseMastery, TransitionHint, RuleFocus, SessionRecap, PoseProgress };
})();
