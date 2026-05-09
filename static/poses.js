/*
 * Sunday · AsanaMind — Pose Library + Rule Engine (v3, production-grade)
 *
 * Designed for MoveNet SinglePose-Lightning running in the browser at ~30 fps.
 * Fixes made in v3:
 *   1. Raised MIN_CONFIDENCE to 0.4 (was 0.3 — too noisy for Lightning).
 *   2. Per-keypoint EMA smoothing so rule state doesn't flap every frame.
 *   3. Side-aware rules — Warrior / Triangle / Tree etc. pick which leg is
 *      forward based on what the user actually does, not a hard-coded side.
 *   4. Rule hysteresis — a rule must fail for N frames before the engine
 *      reports it as a correction, and pass for M frames to clear.
 *   5. Mirror-aware wording — cues say "the leg on the left" instead of
 *      anatomical "your right leg" so users don't get confused in mirrored
 *      video.
 *   6. Diagnostic snapshot — every call returns all evaluated rules with
 *      measured values, so a dev can see exactly why a correction fired.
 *
 * Public globals:
 *   window.ASANA_LIBRARY   — array of 20 pose records
 *   window.asanaData        — alias (legacy)
 *   window.PoseEngine       — { configure(opts), evaluate(kp, name), reset() }
 *   window.PoseImage        — { svg(pose), dataUri(pose) }
 */
(function () {
    'use strict';

    // Tunables — can be overridden via PoseEngine.configure(...)
    const CONFIG = {
        minConfidence: 0.4,          // MoveNet Lightning reliable floor
        smoothing: 0.55,             // EMA factor on keypoint positions (0..1, higher = more stable)
        ruleFailFrames: 7,           // rule must fail this many frames in a row before reporting
        rulePassFrames: 5,           // rule must pass this many frames to clear a reported correction
        mirrored: true,              // video is CSS-mirrored
    };

    // ─────────────────────────────────────────────────────────────
    // GEOMETRY HELPERS
    // ─────────────────────────────────────────────────────────────
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const midpoint = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

    function angleDeg(A, B, C) {
        if (!A || !B || !C) return 180;
        const AB = dist(A, B), BC = dist(B, C), AC = dist(A, C);
        if (AB === 0 || BC === 0) return 180;
        const cos = (AB * AB + BC * BC - AC * AC) / (2 * AB * BC);
        return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
    }

    function torsoLength(kp) {
        const ls = kp.left_shoulder, rs = kp.right_shoulder;
        const lh = kp.left_hip, rh = kp.right_hip;
        if (!ls || !rs || !lh || !rh) return 120;
        return Math.max(40, dist(midpoint(ls, rs), midpoint(lh, rh)));
    }

    // ─────────────────────────────────────────────────────────────
    // EMA smoothing state — one vector per keypoint name
    // ─────────────────────────────────────────────────────────────
    const SMOOTH = {};

    function smoothKeypoints(raw) {
        // raw is the MoveNet array. Return a { name -> {x,y,score} } object
        // with EMA-smoothed positions and only points above minConfidence kept.
        const alpha = CONFIG.smoothing;
        const out = {};
        for (const k of raw) {
            if (!k || !k.name) continue;
            if (k.score < CONFIG.minConfidence) {
                // If we have prior smoothed state, prefer that; else drop.
                if (SMOOTH[k.name] && SMOOTH[k.name].score >= CONFIG.minConfidence * 0.8) {
                    // Mild decay so a lost keypoint eventually ages out.
                    SMOOTH[k.name].score *= 0.9;
                    out[k.name] = { x: SMOOTH[k.name].x, y: SMOOTH[k.name].y, score: SMOOTH[k.name].score };
                }
                continue;
            }
            const prev = SMOOTH[k.name];
            if (!prev) {
                SMOOTH[k.name] = { x: k.x, y: k.y, score: k.score };
            } else {
                SMOOTH[k.name] = {
                    x: alpha * prev.x + (1 - alpha) * k.x,
                    y: alpha * prev.y + (1 - alpha) * k.y,
                    score: Math.max(prev.score, k.score),
                };
            }
            out[k.name] = { x: SMOOTH[k.name].x, y: SMOOTH[k.name].y, score: SMOOTH[k.name].score };
        }
        return out;
    }

    // ─────────────────────────────────────────────────────────────
    // Side detection — figures out which side is forward/standing
    // ─────────────────────────────────────────────────────────────
    // For side-view stances, "front" = whichever ankle is more forward in X
    // (away from the mirror). For Tree pose, "standing" = the ankle lower
    // and more centered on the hips.
    function detectStance(kp) {
        const la = kp.left_ankle, ra = kp.right_ankle;
        const lk = kp.left_knee, rk = kp.right_knee;
        const lh = kp.left_hip, rh = kp.right_hip;

        const out = { forward: null, back: null, standing: null, raised: null };

        if (la && ra && lh && rh) {
            // stance width on X
            const feetDx = Math.abs(la.x - ra.x);
            const hipDx = Math.abs(lh.x - rh.x);
            // If clearly wide (lunge / triangle), forward = ankle farther from hip center
            if (feetDx > hipDx * 1.6) {
                const hipMidX = (lh.x + rh.x) / 2;
                out.forward = Math.abs(la.x - hipMidX) > Math.abs(ra.x - hipMidX) ? 'left' : 'right';
                out.back = out.forward === 'left' ? 'right' : 'left';
            }
            // Standing leg (Tree / Warrior III / Half Moon / Dancer) = lower ankle
            if (Math.abs(la.y - ra.y) > torsoLength(kp) * 0.15) {
                out.standing = la.y > ra.y ? 'left' : 'right';
                out.raised = out.standing === 'left' ? 'right' : 'left';
            }
        }
        return out;
    }

    function resolveSide(sideSpec, stance) {
        // sideSpec is 'left' | 'right' | 'forward' | 'back' | 'standing' | 'raised'
        if (sideSpec === 'left' || sideSpec === 'right') return sideSpec;
        return stance[sideSpec] || null;
    }

    function resolveJoints(joints, stance) {
        // Replace tokens like 'forward_knee' with 'left_knee' or 'right_knee'
        // based on the detected stance. Returns the resolved joints or null
        // if stance couldn't be determined.
        const resolved = [];
        for (const j of joints) {
            const m = j.match(/^(forward|back|standing|raised)_(\w+)$/);
            if (m) {
                const side = stance[m[1]];
                if (!side) return null;
                resolved.push(side + '_' + m[2]);
            } else {
                resolved.push(j);
            }
        }
        return resolved;
    }

    // ─────────────────────────────────────────────────────────────
    // RULE EVALUATORS — now return { pass, measured, label }
    // ─────────────────────────────────────────────────────────────
    function evaluate(kp, rule, stance) {
        const j = resolveJoints(rule.joints, stance);
        if (!j) return { pass: true, skipped: true, reason: 'stance-not-detected' };

        switch (rule.type) {
            case 'angle': {
                const [a, b, c] = j;
                const A = kp[a], B = kp[b], C = kp[c];
                if (!A || !B || !C) return { pass: true, skipped: true, reason: 'missing-keypoint' };
                const deg = angleDeg(A, B, C);
                const [min, max] = rule.range;
                return { pass: deg >= min && deg <= max, measured: Math.round(deg), label: `${b} angle` };
            }
            case 'alignY': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const val = Math.abs(A.y - B.y) / torso;
                return { pass: val <= (rule.tolFrac || 0.15), measured: +val.toFixed(2) };
            }
            case 'alignX': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const val = Math.abs(A.x - B.x) / torso;
                return { pass: val <= (rule.tolFrac || 0.2), measured: +val.toFixed(2) };
            }
            case 'distance': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const ratio = dist(A, B) / torso;
                const min = rule.minFrac == null ? 0 : rule.minFrac;
                const max = rule.maxFrac == null ? Infinity : rule.maxFrac;
                return { pass: ratio >= min && ratio <= max, measured: +ratio.toFixed(2) };
            }
            case 'higher': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const buffer = (rule.bufferFrac || 0) * torso;
                return { pass: A.y + buffer < B.y, measured: +((B.y - A.y) / torso).toFixed(2) };
            }
            case 'lower': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const buffer = (rule.bufferFrac || 0) * torso;
                return { pass: A.y > B.y + buffer, measured: +((A.y - B.y) / torso).toFixed(2) };
            }
            case 'symmetric': {
                const [aL, bL, cL, aR, bR, cR] = j;
                const L = (kp[aL] && kp[bL] && kp[cL]) ? angleDeg(kp[aL], kp[bL], kp[cL]) : null;
                const R = (kp[aR] && kp[bR] && kp[cR]) ? angleDeg(kp[aR], kp[bR], kp[cR]) : null;
                if (L == null || R == null) return { pass: true, skipped: true };
                return { pass: Math.abs(L - R) <= (rule.tolDeg || 15), measured: Math.round(Math.abs(L - R)) };
            }
            case 'horizontalSpan': {
                const A = kp[j[0]], B = kp[j[1]];
                if (!A || !B) return { pass: true, skipped: true };
                const torso = torsoLength(kp);
                const dx = Math.abs(A.x - B.x) / torso, dy = Math.abs(A.y - B.y) / torso;
                return { pass: dx > (rule.minDx || 0.6) && dy < (rule.maxDy || 0.3), measured: `${dx.toFixed(2)}x ${dy.toFixed(2)}y` };
            }
        }
        return { pass: true, skipped: true, reason: 'unknown-rule' };
    }

    // ─────────────────────────────────────────────────────────────
    // REFERENCE POSE TEMPLATES — research-aligned "template matching"
    //
    // Based on the approach from Borthakur 2023 (MDPI Healthcare) and
    // Anjali 2025 (IJRASET Real-Time Yoga Posture Recognition): we take
    // each pose's ideal joint-angle vector and compare the user's live
    // joint-angle vector against it. Distance → continuous accuracy score.
    //
    // Benefits over if/else rules:
    //   • Score is continuous (every degree of correction raises the score)
    //   • One unified algorithm for all 20 poses
    //   • The largest-deviation joint is what we tell the user to fix
    //   • Auto-handles left/right mirroring by matching both orderings
    //
    // Each pose's reference vector is a map of joint name → expected angle.
    // We compute live angles for the SAME joints, then score = max(0, 100 − mean|Δ|/tolerance*50)
    // and the top-N deviations (worst offenders) become the corrections.
    // ─────────────────────────────────────────────────────────────

    // Angle specs: joint label → [startJoint, vertexJoint, endJoint].
    // "vertex" is the joint the angle is measured AT.
    const ANGLE_SPECS = {
        left_elbow:    ['left_shoulder', 'left_elbow', 'left_wrist'],
        right_elbow:   ['right_shoulder', 'right_elbow', 'right_wrist'],
        left_shoulder: ['left_elbow', 'left_shoulder', 'left_hip'],
        right_shoulder:['right_elbow', 'right_shoulder', 'right_hip'],
        left_hip:      ['left_shoulder', 'left_hip', 'left_knee'],
        right_hip:     ['right_shoulder', 'right_hip', 'right_knee'],
        left_knee:     ['left_hip', 'left_knee', 'left_ankle'],
        right_knee:    ['right_hip', 'right_knee', 'right_ankle'],
    };

    function liveAngles(kp) {
        const angles = {};
        for (const name of Object.keys(ANGLE_SPECS)) {
            const [a, b, c] = ANGLE_SPECS[name];
            if (kp[a] && kp[b] && kp[c]) {
                angles[name] = angleDeg(kp[a], kp[b], kp[c]);
            }
        }
        return angles;
    }

    // Reference vectors captured from the ideal form of each pose.
    // Source: mean of published yoga biomechanics references + manual
    // tuning against the ChatGPT reference images in assets/poses/.
    // Values are in degrees (0-180 convention used by angleDeg).
    const REFERENCE_VECTORS = {
        // --- BEGINNER ---
        'Tadasana':              { left_knee:180, right_knee:180, left_hip:180, right_hip:180, left_shoulder:10, right_shoulder:10, left_elbow:175, right_elbow:175 },
        'Urdhva Hastasana':      { left_knee:180, right_knee:180, left_hip:180, right_hip:180, left_shoulder:170, right_shoulder:170, left_elbow:170, right_elbow:170 },
        'Anjali Mudra':          { left_knee:180, right_knee:180, left_hip:180, right_hip:180, left_shoulder:30, right_shoulder:30, left_elbow:70, right_elbow:70 },
        'Vrikshasana':           { left_knee:180, right_knee:55,  left_hip:180, right_hip:110, left_shoulder:160, right_shoulder:160, left_elbow:70, right_elbow:70 },
        'Uttanasana':            { left_knee:170, right_knee:170, left_hip:30,  right_hip:30,  left_shoulder:160, right_shoulder:160, left_elbow:170, right_elbow:170 },
        'Sukhasana':             { left_knee:60,  right_knee:60,  left_hip:90,  right_hip:90,  left_shoulder:30, right_shoulder:30, left_elbow:170, right_elbow:170 },
        'Dandasana':             { left_knee:175, right_knee:175, left_hip:90,  right_hip:90,  left_shoulder:20, right_shoulder:20, left_elbow:170, right_elbow:170 },
        'Baddha Konasana':       { left_knee:40,  right_knee:40,  left_hip:80,  right_hip:80,  left_shoulder:20, right_shoulder:20, left_elbow:150, right_elbow:150 },
        'Paschimottanasana':     { left_knee:170, right_knee:170, left_hip:35,  right_hip:35,  left_shoulder:50, right_shoulder:50, left_elbow:170, right_elbow:170 },
        'Balasana':              { left_knee:40,  right_knee:40,  left_hip:40,  right_hip:40,  left_shoulder:170, right_shoulder:170, left_elbow:170, right_elbow:170 },
        // --- INTERMEDIATE ---
        'Adho Mukha Svanasana':  { left_knee:170, right_knee:170, left_hip:75,  right_hip:75,  left_shoulder:170, right_shoulder:170, left_elbow:175, right_elbow:175 },
        'Virabhadrasana I':      { left_knee:170, right_knee:95,  left_hip:130, right_hip:110, left_shoulder:170, right_shoulder:170, left_elbow:170, right_elbow:170 },
        'Virabhadrasana II':     { left_knee:170, right_knee:95,  left_hip:165, right_hip:135, left_shoulder:90,  right_shoulder:90,  left_elbow:175, right_elbow:175 },
        'Utthita Trikonasana':   { left_knee:175, right_knee:175, left_hip:100, right_hip:60,  left_shoulder:170, right_shoulder:90,  left_elbow:175, right_elbow:175 },
        'Utkatasana':            { left_knee:110, right_knee:110, left_hip:110, right_hip:110, left_shoulder:170, right_shoulder:170, left_elbow:170, right_elbow:170 },
        'Utthita Parsvakonasana':{ left_knee:170, right_knee:95,  left_hip:140, right_hip:70,  left_shoulder:170, right_shoulder:75,  left_elbow:170, right_elbow:170 },
        'Setu Bandhasana':       { left_knee:95,  right_knee:95,  left_hip:155, right_hip:155, left_shoulder:40, right_shoulder:40, left_elbow:170, right_elbow:170 },
        // --- ADVANCED ---
        'Virabhadrasana III':    { left_knee:175, right_knee:175, left_hip:165, right_hip:90,  left_shoulder:170, right_shoulder:170, left_elbow:170, right_elbow:170 },
        'Ardha Chandrasana':     { left_knee:175, right_knee:175, left_hip:150, right_hip:90,  left_shoulder:170, right_shoulder:100, left_elbow:175, right_elbow:175 },
        'Natarajasana':          { left_knee:175, right_knee:45,  left_hip:175, right_hip:100, left_shoulder:170, right_shoulder:120, left_elbow:170, right_elbow:100 },
    };

    // Human-readable correction messages per joint, with mirror-safe wording.
    const JOINT_LABELS = {
        left_knee:   'the knee on your right of the screen',
        right_knee:  'the knee on your left of the screen',
        left_hip:    'the hip on your right',
        right_hip:   'the hip on your left',
        left_shoulder:'the shoulder on your right',
        right_shoulder:'the shoulder on your left',
        left_elbow:  'the elbow on your right',
        right_elbow: 'the elbow on your left',
    };

    // Tolerance per joint type — chosen from empirical MoveNet jitter plus
    // natural range of motion variance across body types.
    const JOINT_TOLERANCE = {
        left_knee: 22, right_knee: 22,        // knees: ±22° allowed
        left_hip: 25, right_hip: 25,          // hips have wide range across builds
        left_shoulder: 28, right_shoulder: 28,// shoulder joint very noisy
        left_elbow: 25, right_elbow: 25,      // elbow range varies
    };

    function evaluateTemplate(kp, poseName) {
        const ref = REFERENCE_VECTORS[poseName];
        if (!ref) return null;

        const live = liveAngles(kp);

        // For symmetric poses we also consider the LEFT-RIGHT-flipped
        // reference vector and pick whichever matches better. This means
        // "Warrior I with left foot forward" scores the same as
        // "Warrior I with right foot forward" — we don't penalize the user
        // for setting up on either side.
        const flipped = {};
        for (const k of Object.keys(ref)) {
            const mirrored = k.startsWith('left_') ? 'right_' + k.slice(5)
                          : k.startsWith('right_') ? 'left_' + k.slice(6) : k;
            flipped[mirrored] = ref[k];
        }

        function diffFor(refVec) {
            const deltas = {};
            let totalWeightedErr = 0;
            let totalWeight = 0;
            let measured = 0;
            for (const joint of Object.keys(refVec)) {
                const userA = live[joint];
                if (userA == null) continue;
                const refA = refVec[joint];
                const tol = JOINT_TOLERANCE[joint] || 20;
                const delta = Math.abs(userA - refA);
                // Error is how many "tolerance units" the user is off.
                const err = Math.max(0, delta - tol * 0.4) / tol;
                deltas[joint] = { delta: Math.round(delta), tolerance: tol, err: +err.toFixed(2), user: Math.round(userA), ref: refA };
                totalWeightedErr += err;
                totalWeight += 1;
                measured++;
            }
            return { deltas, avgErr: totalWeight > 0 ? totalWeightedErr / totalWeight : 1, measured };
        }

        const normal = diffFor(ref);
        const mirrored = diffFor(flipped);
        const best = normal.avgErr <= mirrored.avgErr ? normal : mirrored;

        // Score: 100 when avgErr==0, decays to 0 by avgErr==1.2
        const score = Math.max(0, Math.min(100, Math.round(100 * (1 - best.avgErr / 1.2))));

        // Pick the top 3 worst deviations as corrections, sorted by err
        const worst = Object.entries(best.deltas)
            .filter(([, v]) => v.err > 0.15)
            .sort((a, b) => b[1].err - a[1].err)
            .slice(0, 3)
            .map(([joint, v]) => {
                const label = JOINT_LABELS[joint] || joint;
                let direction = '';
                if (v.user > v.ref + 5) direction = 'less';
                else if (v.user < v.ref - 5) direction = 'more';
                // Shape guidance text per joint-type
                let msg;
                if (joint.endsWith('_knee')) {
                    msg = direction === 'more' ? `Bend ${label} more` : direction === 'less' ? `Straighten ${label}` : `Adjust ${label}`;
                } else if (joint.endsWith('_hip')) {
                    msg = direction === 'more' ? `Fold deeper at ${label}` : direction === 'less' ? `Open ${label} taller` : `Square ${label}`;
                } else if (joint.endsWith('_shoulder')) {
                    msg = direction === 'more' ? `Raise ${label} higher` : direction === 'less' ? `Soften ${label} down` : `Align ${label}`;
                } else if (joint.endsWith('_elbow')) {
                    msg = direction === 'more' ? `Bend ${label} more` : direction === 'less' ? `Straighten ${label}` : `Adjust ${label}`;
                } else {
                    msg = `Adjust ${label}`;
                }
                return {
                    message: msg,
                    joint,
                    delta: v.delta,
                    user: v.user,
                    ref: v.ref,
                    severity: v.err > 0.6 ? 'red' : v.err > 0.3 ? 'yellow' : 'blue',
                    priority: v.err > 0.6 ? 1 : v.err > 0.3 ? 2 : 3,
                };
            });

        return { score, corrections: worst, deltas: best.deltas, usedMirror: best === mirrored };
    }


    const FAIL_STREAK = {};   // rule.id → frames failing
    const PASS_STREAK = {};   // rule.id → frames passing (after a fail)
    const REPORTED = {};      // rule.id → currently visible to user?

    function ruleId(poseName, idx) { return poseName + '::' + idx; }

    const PoseEngine = {
        configure(opts) { Object.assign(CONFIG, opts || {}); },
        reset() {
            for (const k of Object.keys(SMOOTH)) delete SMOOTH[k];
            for (const k of Object.keys(FAIL_STREAK)) delete FAIL_STREAK[k];
            for (const k of Object.keys(PASS_STREAK)) delete PASS_STREAK[k];
            for (const k of Object.keys(REPORTED)) delete REPORTED[k];
        },
        getStance(rawKeypoints) {
            const kp = smoothKeypoints(rawKeypoints);
            return detectStance(kp);
        },

        evaluate(rawKeypoints, poseName) {
            const pose = ASANA_LIBRARY.find(p => p.name === poseName);
            if (!pose) {
                return { corrections: [{ message: 'Pose not configured', color: 'yellow', priority: 3, affected: [] }], score: 0, diagnostics: [] };
            }

            // Smooth keypoints before evaluating anything
            const kp = smoothKeypoints(rawKeypoints);

            // Global visibility — do we see enough of the body?
            const required = pose.required || ['left_hip', 'right_hip', 'left_shoulder', 'right_shoulder', 'nose'];
            const missing = required.filter(r => !kp[r]);
            if (missing.length > 2) {
                return {
                    corrections: [{ message: 'Step back so your full body is in frame', affected: required, color: 'red', priority: 1 }],
                    score: 0,
                    diagnostics: [{ rule: 'visibility', missing }],
                };
            }

            // --- PRIMARY PATH: reference-pose template matching ---
            // If this pose has a reference angle vector, use it as the score
            // and the primary source of corrections. This is the algorithm
            // from Borthakur 2023 and Anjali 2025, adapted to 20 poses.
            const tpl = evaluateTemplate(kp, poseName);
            if (tpl) {
                // Build diagnostics from template deltas for the on-screen panel.
                const tplDiag = Object.entries(tpl.deltas).map(([joint, v]) => ({
                    idx: joint,
                    pass: v.err <= 0.3,
                    measured: `${v.user}° (target ${v.ref}°)`,
                    message: `${joint} angle`,
                    priority: v.err > 0.6 ? 1 : v.err > 0.3 ? 2 : 3,
                    failStreak: 0,
                    reported: v.err > 0.3,
                }));

                // Also run the declarative rules for visibility/stance-only
                // checks, but skip any whose joints overlap with template
                // corrections (to avoid contradictory or duplicate cues).
                const stance = detectStance(kp);
                const ruleDiag = [];
                const ruleCorrections = [];
                const templateJoints = new Set(tpl.corrections.map(c => c.joint));
                let extraPriorityOneCount = 0;
                for (let i = 0; i < pose.rules.length; i++) {
                    const rule = pose.rules[i];
                    const result = evaluate(kp, rule, stance);
                    if (result.skipped) continue;
                    ruleDiag.push({
                        idx: i,
                        pass: !!result.pass,
                        measured: result.measured,
                        message: rule.message,
                        priority: rule.priority || 3,
                    });
                    // Skip rules whose joints are already handled by the template
                    const ruleJoints = rule.joints || [];
                    const overlap = ruleJoints.some(rj => {
                        const resolved = rj; // simple compare; template joints are simple left_/right_ forms
                        return templateJoints.has(resolved);
                    });
                    if (overlap) continue;
                    // Only surface non-overlapping rule corrections when score is low
                    if (!result.pass && rule.priority === 1 && tpl.score < 75) {
                        extraPriorityOneCount++;
                        if (extraPriorityOneCount <= 1) {
                            ruleCorrections.push({
                                message: rewriteForMirror(rule.message),
                                shortMessage: rewriteForMirror(rule.shortMessage || shortenCue(rule.message)),
                                color: 'red',
                                priority: 1,
                            });
                        }
                    }
                }

                // Hysteresis — only report a template correction if it's been
                // bad for several frames. Use the "joint" as a stable id.
                const reportedCorrections = [];
                for (const c of tpl.corrections) {
                    const id = poseName + '::' + c.joint;
                    if (c.severity !== 'blue') {
                        FAIL_STREAK[id] = (FAIL_STREAK[id] || 0) + 1;
                        PASS_STREAK[id] = 0;
                        if (FAIL_STREAK[id] >= CONFIG.ruleFailFrames) REPORTED[id] = true;
                    } else {
                        FAIL_STREAK[id] = 0;
                        PASS_STREAK[id] = (PASS_STREAK[id] || 0) + 1;
                        if (PASS_STREAK[id] >= CONFIG.rulePassFrames) REPORTED[id] = false;
                    }
                    if (REPORTED[id]) {
                        reportedCorrections.push({
                            message: c.message,
                            shortMessage: c.shortMessage || shortenCue(c.message),
                            color: c.severity === 'red' ? 'red' : c.severity === 'yellow' ? 'yellow' : 'blue',
                            priority: c.priority,
                            affected: [c.joint],
                        });
                    }
                }

                // Combine: rule-based red cues first, then template cues
                const combined = [...ruleCorrections, ...reportedCorrections];
                combined.sort((a, b) => (a.priority || 5) - (b.priority || 5));
                const top = combined.slice(0, 3);

                if (top.length === 0) {
                    top.push({ message: `Beautiful ${pose.name}. Hold and breathe.`, affected: [], color: 'green', priority: 0 });
                } else if (tpl.score >= 85) {
                    top.unshift({ message: 'Close. One small refinement.', affected: [], color: 'blue', priority: 0 });
                }

                return {
                    corrections: top,
                    score: tpl.score,
                    diagnostics: [...tplDiag, ...ruleDiag],
                    stance,
                    usedMirror: tpl.usedMirror,
                };
            }

            // --- FALLBACK PATH: old rule-only evaluator ---
            // (only used if pose has no reference vector; shouldn't happen
            //  for the 20 curated poses but kept for robustness.)
            if (!pose.rules || !pose.rules.length) {
                return { corrections: [{ message: 'Hold the pose calmly and breathe.', color: 'green', priority: 0, affected: [] }], score: 80, diagnostics: [] };
            }

            // Detect the user's stance so side-aware rules can resolve
            const stance = detectStance(kp);

            // Evaluate all rules
            const diagnostics = [];
            const corrections = [];
            let totalWeight = 0, passWeight = 0;

            for (let i = 0; i < pose.rules.length; i++) {
                const rule = pose.rules[i];
                const weight = rule.priority === 1 ? 3 : rule.priority === 2 ? 2 : 1;
                totalWeight += weight;

                const result = evaluate(kp, rule, stance);
                const id = ruleId(poseName, i);

                if (result.skipped) {
                    passWeight += weight;
                    diagnostics.push({ idx: i, skipped: true, reason: result.reason, message: rule.message });
                    continue;
                }

                if (result.pass) {
                    passWeight += weight;
                    FAIL_STREAK[id] = 0;
                    PASS_STREAK[id] = (PASS_STREAK[id] || 0) + 1;
                    if (REPORTED[id] && PASS_STREAK[id] >= CONFIG.rulePassFrames) {
                        REPORTED[id] = false;
                    }
                } else {
                    FAIL_STREAK[id] = (FAIL_STREAK[id] || 0) + 1;
                    PASS_STREAK[id] = 0;
                    // Priority 1 (safety) rules report after 4 frames (~130 ms)
                    // instead of the default 7 (~230 ms) — faster is safer.
                    const failThreshold = (rule.priority === 1) ? 4 : CONFIG.ruleFailFrames;
                    if (FAIL_STREAK[id] >= failThreshold) {
                        REPORTED[id] = true;
                    }
                }

                diagnostics.push({
                    idx: i,
                    pass: !!result.pass,
                    measured: result.measured,
                    message: rule.message,
                    priority: rule.priority || 3,
                    failStreak: FAIL_STREAK[id] || 0,
                    reported: !!REPORTED[id],
                });

                if (REPORTED[id]) {
                    // Derive a short-form message (2-4 words) for priority 1
                    // interrupts. If the rule author supplied one, use it; else
                    // synthesise from the long form.
                    const shortMessage = rule.shortMessage || shortenCue(rule.message);
                    corrections.push({
                        id,
                        message: rewriteForMirror(rule.message),
                        shortMessage: rewriteForMirror(shortMessage),
                        affected: rule.affected || rule.joints || [],
                        color: rule.severity || (rule.priority === 1 ? 'red' : 'yellow'),
                        priority: rule.priority || 3,
                        measured: result.measured,
                    });
                }
            }

            const score = totalWeight > 0 ? Math.round((passWeight / totalWeight) * 100) : 100;

            corrections.sort((a, b) => (a.priority || 5) - (b.priority || 5));
            const top = corrections.slice(0, 3);

            if (top.length === 0) {
                top.push({ message: `Beautiful ${pose.name}. Hold and breathe.`, affected: [], color: 'green', priority: 0 });
            } else if (score >= 85) {
                top.unshift({ message: 'Close. One small refinement.', affected: [], color: 'blue', priority: 0 });
            }

            return { corrections: top, score, diagnostics, stance };
        },
    };

    /**
     * Shorten a verbose cue to 2-5 words for priority-1 TTS interrupts.
     * Uses a compact keyword map; falls back to the first 4 words of the cue.
     * Keeping this deterministic avoids any LLM dependency.
     */
    function shortenCue(msg) {
        if (!msg) return msg;
        const lower = msg.toLowerCase();
        const DICT = [
            [/front knee.*ankle|knee over.*ankle|knee tracking/, 'Knee over ankle'],
            [/front knee.*toes|knee past.*toes/, 'Knee back, not past toes'],
            [/straighten.*(standing|back) leg|standing leg strong/, 'Straighten the leg'],
            [/hips level|keep the hips level|do not open.*hip/, 'Level the hips'],
            [/square.*hips|hips square|turn.*hip forward/, 'Square the hips'],
            [/lift.*chest|lift the chest|chest up/, 'Lift the chest'],
            [/open.*chest/, 'Open the chest'],
            [/lengthen.*spine|tall spine|spine long/, 'Lengthen the spine'],
            [/relax.*shoulders?|shoulders? down|drop.*shoulders?/, 'Drop the shoulders'],
            [/arms? (parallel|level|straight|overhead)/, 'Extend the arms'],
            [/engage.*core|core on|active core/, 'Engage the core'],
            [/press.*feet|root.*foot|ground the feet|weight even/, 'Root the feet'],
            [/flex.*foot|flex the foot/, 'Flex the foot'],
            [/gaze (forward|over|at)/, 'Soften the gaze'],
            [/breathe|breath/, 'Breathe'],
            [/hold|steady/, 'Hold steady'],
        ];
        for (const [re, out] of DICT) if (re.test(lower)) return out;
        // Fallback — first four meaningful words.
        const words = msg.replace(/[^a-zA-Z ,]/g, '').split(/\s+/).filter(w => w.length > 2);
        return words.slice(0, 4).join(' ') || msg;
    }

    function rewriteForMirror(msg) {
        // If the video is CSS-mirrored, "your right" (as seen by MoveNet)
        // appears on the viewer's left. For clarity we rewrite "right/left"
        // to "the side on your left/right of the screen" — but only if the
        // cue is about a joint that has a side. Keep generic cues alone.
        if (!CONFIG.mirrored) return msg;
        // Keep cues like "Level your hips" and "Lift the chest" untouched.
        // Only tweak "left X" / "right X" wording.
        return msg
            .replace(/\bleft arm\b/gi, 'the arm on your right')
            .replace(/\bright arm\b/gi, 'the arm on your left')
            .replace(/\bleft leg\b/gi, 'the leg on your right')
            .replace(/\bright leg\b/gi, 'the leg on your left')
            .replace(/\bleft knee\b/gi, 'the knee on your right')
            .replace(/\bright knee\b/gi, 'the knee on your left')
            .replace(/\bleft hand\b/gi, 'the hand on your right')
            .replace(/\bright hand\b/gi, 'the hand on your left');
    }

    // ─────────────────────────────────────────────────────────────
    // POSE IMAGE RENDERER
    // Renders an SVG silhouette from a pose's reference keypoints.
    // Coordinates are in a 0..1 normalised space (origin top-left).
    // ─────────────────────────────────────────────────────────────
    // 17 MoveNet keypoints in order.
    const BONES = [];

    // Filled human silhouette: torso as a polygon, limbs as tapered lines,
    // head + hands + feet as caps. Looks like a person, not a wire frame.
    function poseSvg(pose, opts) {
        opts = opts || {};
        const w = opts.width || 400;
        const h = opts.height || 500;
        const bg = opts.bg || '#F3EEE5';
        const body = opts.body || '#1E2E1F';
        const accent = opts.accent || '#D4A04A';
        const kp = pose.referenceKeypoints || {};

        const padX = w * 0.12, padY = h * 0.08;
        const innerW = w - padX * 2, innerH = h - padY * 2;
        const toX = v => padX + v * innerW;
        const toY = v => padY + v * innerH;

        const unit = Math.min(innerW, innerH);
        const W_TORSO_CAP = unit * 0.09;
        const W_UPPER_ARM = unit * 0.062;
        const W_LOWER_ARM = unit * 0.048;
        const W_UPPER_LEG = unit * 0.085;
        const W_LOWER_LEG = unit * 0.062;
        const HEAD_R = unit * 0.07;
        const NECK_W = unit * 0.07;

        // Tapered limb: thick at start, thinner at end, drawn as two overlapping rounded lines.
        function limb(a, b, wStart, wEnd) {
            if (!a || !b) return '';
            const ax = toX(a.x), ay = toY(a.y);
            const bx = toX(b.x), by = toY(b.y);
            const mx = (ax + bx) / 2, my = (ay + by) / 2;
            const wMid = (wStart + wEnd) / 2;
            return `<line x1="${ax}" y1="${ay}" x2="${mx}" y2="${my}" stroke="${body}" stroke-width="${wStart}" stroke-linecap="round"/>`
                 + `<line x1="${mx}" y1="${my}" x2="${bx}" y2="${by}" stroke="${body}" stroke-width="${wEnd}" stroke-linecap="round"/>`;
        }

        // Torso: a filled polygon with rounded caps
        let torso = '';
        if (kp.left_shoulder && kp.right_shoulder && kp.left_hip && kp.right_hip) {
            const ls = kp.left_shoulder, rs = kp.right_shoulder;
            const lh = kp.left_hip, rh = kp.right_hip;
            torso = `<polygon points="${toX(ls.x)},${toY(ls.y)} ${toX(rs.x)},${toY(rs.y)} ${toX(rh.x)},${toY(rh.y)} ${toX(lh.x)},${toY(lh.y)}" fill="${body}"/>`
                  + `<circle cx="${toX(ls.x)}" cy="${toY(ls.y)}" r="${W_TORSO_CAP}" fill="${body}"/>`
                  + `<circle cx="${toX(rs.x)}" cy="${toY(rs.y)}" r="${W_TORSO_CAP}" fill="${body}"/>`
                  + `<circle cx="${toX(lh.x)}" cy="${toY(lh.y)}" r="${W_TORSO_CAP * 0.85}" fill="${body}"/>`
                  + `<circle cx="${toX(rh.x)}" cy="${toY(rh.y)}" r="${W_TORSO_CAP * 0.85}" fill="${body}"/>`;
        }

        // Limbs
        let limbs = '';
        limbs += limb(kp.left_shoulder, kp.left_elbow, W_UPPER_ARM, W_UPPER_ARM * 0.85);
        limbs += limb(kp.left_elbow, kp.left_wrist, W_LOWER_ARM, W_LOWER_ARM * 0.72);
        limbs += limb(kp.right_shoulder, kp.right_elbow, W_UPPER_ARM, W_UPPER_ARM * 0.85);
        limbs += limb(kp.right_elbow, kp.right_wrist, W_LOWER_ARM, W_LOWER_ARM * 0.72);
        limbs += limb(kp.left_hip, kp.left_knee, W_UPPER_LEG, W_UPPER_LEG * 0.85);
        limbs += limb(kp.left_knee, kp.left_ankle, W_LOWER_LEG, W_LOWER_LEG * 0.7);
        limbs += limb(kp.right_hip, kp.right_knee, W_UPPER_LEG, W_UPPER_LEG * 0.85);
        limbs += limb(kp.right_knee, kp.right_ankle, W_LOWER_LEG, W_LOWER_LEG * 0.7);

        // Neck + head
        let head = '';
        if (kp.nose && kp.left_shoulder && kp.right_shoulder) {
            const midSx = (kp.left_shoulder.x + kp.right_shoulder.x) / 2;
            const midSy = (kp.left_shoulder.y + kp.right_shoulder.y) / 2;
            head  = `<line x1="${toX(midSx)}" y1="${toY(midSy)}" x2="${toX(kp.nose.x)}" y2="${toY(kp.nose.y)}" stroke="${body}" stroke-width="${NECK_W}" stroke-linecap="round"/>`;
            head += `<circle cx="${toX(kp.nose.x)}" cy="${toY(kp.nose.y)}" r="${HEAD_R}" fill="${body}"/>`;
            head += `<circle cx="${toX(kp.nose.x) - HEAD_R * 0.3}" cy="${toY(kp.nose.y) - HEAD_R * 0.35}" r="${HEAD_R * 0.22}" fill="${accent}" opacity="0.4"/>`;
        }

        // Hands & feet caps
        const hands = ['left_wrist', 'right_wrist']
            .filter(n => kp[n])
            .map(n => `<circle cx="${toX(kp[n].x)}" cy="${toY(kp[n].y)}" r="${W_LOWER_ARM * 0.55}" fill="${body}"/>`)
            .join('');
        const feet = ['left_ankle', 'right_ankle']
            .filter(n => kp[n])
            .map(n => `<ellipse cx="${toX(kp[n].x)}" cy="${toY(kp[n].y) + 2}" rx="${W_LOWER_LEG * 0.95}" ry="${W_LOWER_LEG * 0.42}" fill="${body}"/>`)
            .join('');

        // Ambient glow + soft ground shadow
        const glowA = `<circle cx="${w*0.82}" cy="${h*0.2}" r="${unit*0.22}" fill="${accent}" opacity="0.16"/>`;
        const glowB = `<circle cx="${w*0.15}" cy="${h*0.85}" r="${unit*0.27}" fill="#B8573E" opacity="0.10"/>`;

        const ankleYs = ['left_ankle', 'right_ankle'].filter(n => kp[n]).map(n => toY(kp[n].y));
        let shadow = '';
        if (ankleYs.length) {
            const sy = Math.max(...ankleYs) + 6;
            shadow = `<ellipse cx="${w/2}" cy="${sy}" rx="${unit*0.22}" ry="${unit*0.035}" fill="${body}" opacity="0.12"/>`;
        }

        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="100%" height="100%" role="img" aria-label="${pose.name} silhouette">
            <rect width="${w}" height="${h}" fill="${bg}"/>
            ${glowA}${glowB}${shadow}
            ${limbs}
            ${torso}
            ${hands}${feet}
            ${head}
        </svg>`;
    }

    function toDataUri(svg) {
        return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
    }

    const PoseImage = {
        svg: (pose, opts) => poseSvg(pose, opts),
        dataUri: (pose, opts) => toDataUri(poseSvg(pose, opts)),
    };

    // ─────────────────────────────────────────────────────────────
    // REFERENCE KEYPOINT SHAPES
    // Each shape is hand-tuned so the silhouette looks clearly like
    // the pose. Origin top-left, 0..1 normalised.
    // Helper K(n, x, y) just makes the table below readable.
    // ─────────────────────────────────────────────────────────────
    const K = (x, y) => ({ x, y });

    // Standing front-view template (Tadasana baseline)
    const KP_TADASANA = {
        nose:            K(0.50, 0.10),
        left_eye:        K(0.48, 0.09),  right_eye:       K(0.52, 0.09),
        left_shoulder:   K(0.42, 0.22),  right_shoulder:  K(0.58, 0.22),
        left_elbow:      K(0.40, 0.38),  right_elbow:     K(0.60, 0.38),
        left_wrist:      K(0.39, 0.54),  right_wrist:     K(0.61, 0.54),
        left_hip:        K(0.44, 0.52),  right_hip:       K(0.56, 0.52),
        left_knee:       K(0.45, 0.74),  right_knee:      K(0.55, 0.74),
        left_ankle:      K(0.46, 0.96),  right_ankle:     K(0.54, 0.96),
    };

    const KP_URDHVA = {  // Upward salute — arms straight up
        nose:            K(0.50, 0.16),
        left_shoulder:   K(0.42, 0.26),  right_shoulder:  K(0.58, 0.26),
        left_elbow:      K(0.42, 0.12),  right_elbow:     K(0.58, 0.12),
        left_wrist:      K(0.43, 0.00),  right_wrist:     K(0.57, 0.00),
        left_hip:        K(0.44, 0.54),  right_hip:       K(0.56, 0.54),
        left_knee:       K(0.45, 0.75),  right_knee:      K(0.55, 0.75),
        left_ankle:      K(0.46, 0.96),  right_ankle:     K(0.54, 0.96),
    };

    const KP_ANJALI = {  // Prayer at heart
        nose:            K(0.50, 0.10),
        left_shoulder:   K(0.42, 0.22),  right_shoulder:  K(0.58, 0.22),
        left_elbow:      K(0.36, 0.32),  right_elbow:     K(0.64, 0.32),
        left_wrist:      K(0.49, 0.36),  right_wrist:     K(0.51, 0.36),
        left_hip:        K(0.44, 0.52),  right_hip:       K(0.56, 0.52),
        left_knee:       K(0.45, 0.74),  right_knee:      K(0.55, 0.74),
        left_ankle:      K(0.46, 0.96),  right_ankle:     K(0.54, 0.96),
    };

    const KP_VRIKSHASANA = {  // Tree — right foot on left inner thigh, hands at heart
        nose:            K(0.50, 0.10),
        left_shoulder:   K(0.42, 0.22),  right_shoulder:  K(0.58, 0.22),
        left_elbow:      K(0.36, 0.32),  right_elbow:     K(0.64, 0.32),
        left_wrist:      K(0.49, 0.36),  right_wrist:     K(0.51, 0.36),
        left_hip:        K(0.44, 0.52),  right_hip:       K(0.56, 0.52),
        left_knee:       K(0.46, 0.74),  right_knee:      K(0.70, 0.60),
        left_ankle:      K(0.47, 0.96),  right_ankle:     K(0.50, 0.55),
    };

    const KP_UTTANASANA = {  // Standing forward fold (side view, facing right)
        nose:            K(0.60, 0.68),
        left_shoulder:   K(0.54, 0.56),  right_shoulder:  K(0.56, 0.58),
        left_elbow:      K(0.58, 0.74),  right_elbow:     K(0.60, 0.76),
        left_wrist:      K(0.62, 0.92),  right_wrist:     K(0.64, 0.94),
        left_hip:        K(0.44, 0.50),  right_hip:       K(0.46, 0.50),
        left_knee:       K(0.46, 0.72),  right_knee:      K(0.48, 0.72),
        left_ankle:      K(0.48, 0.96),  right_ankle:     K(0.50, 0.96),
    };

    const KP_SUKHASANA = {  // Easy seated
        nose:            K(0.50, 0.20),
        left_shoulder:   K(0.40, 0.34),  right_shoulder:  K(0.60, 0.34),
        left_elbow:      K(0.32, 0.50),  right_elbow:     K(0.68, 0.50),
        left_wrist:      K(0.30, 0.66),  right_wrist:     K(0.70, 0.66),
        left_hip:        K(0.44, 0.66),  right_hip:       K(0.56, 0.66),
        left_knee:       K(0.22, 0.80),  right_knee:      K(0.78, 0.80),
        left_ankle:      K(0.40, 0.88),  right_ankle:     K(0.60, 0.88),
    };

    const KP_DANDASANA = {  // Staff seated (side view)
        nose:            K(0.32, 0.16),
        left_shoulder:   K(0.32, 0.30),  right_shoulder:  K(0.34, 0.30),
        left_elbow:      K(0.32, 0.50),  right_elbow:     K(0.34, 0.50),
        left_wrist:      K(0.32, 0.66),  right_wrist:     K(0.34, 0.66),
        left_hip:        K(0.34, 0.66),  right_hip:       K(0.36, 0.66),
        left_knee:       K(0.60, 0.66),  right_knee:      K(0.60, 0.68),
        left_ankle:      K(0.90, 0.66),  right_ankle:     K(0.90, 0.68),
    };

    const KP_BADDHA = {  // Bound angle seated (front)
        nose:            K(0.50, 0.22),
        left_shoulder:   K(0.40, 0.36),  right_shoulder:  K(0.60, 0.36),
        left_elbow:      K(0.34, 0.54),  right_elbow:     K(0.66, 0.54),
        left_wrist:      K(0.42, 0.70),  right_wrist:     K(0.58, 0.70),
        left_hip:        K(0.44, 0.68),  right_hip:       K(0.56, 0.68),
        left_knee:       K(0.18, 0.82),  right_knee:      K(0.82, 0.82),
        left_ankle:      K(0.50, 0.76),  right_ankle:     K(0.50, 0.76),
    };

    const KP_PASCHIMO = {  // Seated forward fold (side)
        nose:            K(0.46, 0.58),
        left_shoulder:   K(0.40, 0.50),  right_shoulder:  K(0.42, 0.52),
        left_elbow:      K(0.58, 0.56),  right_elbow:     K(0.60, 0.58),
        left_wrist:      K(0.80, 0.62),  right_wrist:     K(0.82, 0.64),
        left_hip:        K(0.34, 0.58),  right_hip:       K(0.36, 0.58),
        left_knee:       K(0.60, 0.58),  right_knee:      K(0.60, 0.60),
        left_ankle:      K(0.90, 0.58),  right_ankle:     K(0.90, 0.60),
    };

    const KP_BALASANA = {  // Child (side)
        nose:            K(0.50, 0.78),
        left_shoulder:   K(0.48, 0.70),  right_shoulder:  K(0.50, 0.72),
        left_elbow:      K(0.64, 0.76),  right_elbow:     K(0.66, 0.78),
        left_wrist:      K(0.82, 0.82),  right_wrist:     K(0.84, 0.84),
        left_hip:        K(0.36, 0.60),  right_hip:       K(0.38, 0.60),
        left_knee:       K(0.24, 0.82),  right_knee:      K(0.26, 0.82),
        left_ankle:      K(0.34, 0.92),  right_ankle:     K(0.36, 0.92),
    };

    const KP_DOWNDOG = {  // Downward dog (side, inverted V)
        nose:            K(0.36, 0.68),
        left_shoulder:   K(0.30, 0.58),  right_shoulder:  K(0.32, 0.60),
        left_elbow:      K(0.24, 0.76),  right_elbow:     K(0.26, 0.78),
        left_wrist:      K(0.18, 0.92),  right_wrist:     K(0.20, 0.94),
        left_hip:        K(0.58, 0.20),  right_hip:       K(0.60, 0.22),
        left_knee:       K(0.72, 0.52),  right_knee:      K(0.74, 0.54),
        left_ankle:      K(0.86, 0.90),  right_ankle:     K(0.88, 0.92),
    };

    const KP_VIR1 = {  // Warrior I (side — right leg forward, arms up)
        nose:            K(0.56, 0.18),
        left_shoulder:   K(0.50, 0.28),  right_shoulder:  K(0.58, 0.28),
        left_elbow:      K(0.48, 0.14),  right_elbow:     K(0.60, 0.14),
        left_wrist:      K(0.46, 0.00),  right_wrist:     K(0.62, 0.00),
        left_hip:        K(0.42, 0.52),  right_hip:       K(0.50, 0.52),
        left_knee:       K(0.24, 0.76),  right_knee:      K(0.66, 0.70),
        left_ankle:      K(0.14, 0.96),  right_ankle:     K(0.72, 0.96),
    };

    const KP_VIR2 = {  // Warrior II (front — wide stance, arms out)
        nose:            K(0.50, 0.14),
        left_shoulder:   K(0.40, 0.26),  right_shoulder:  K(0.60, 0.26),
        left_elbow:      K(0.22, 0.26),  right_elbow:     K(0.78, 0.26),
        left_wrist:      K(0.04, 0.26),  right_wrist:     K(0.96, 0.26),
        left_hip:        K(0.42, 0.56),  right_hip:       K(0.58, 0.56),
        left_knee:       K(0.22, 0.74),  right_knee:      K(0.76, 0.68),
        left_ankle:      K(0.10, 0.96),  right_ankle:     K(0.90, 0.96),
    };

    const KP_TRIKON = {  // Triangle (side — right leg forward)
        nose:            K(0.70, 0.42),
        left_shoulder:   K(0.50, 0.34),  right_shoulder:  K(0.60, 0.48),
        left_elbow:      K(0.48, 0.20),  right_elbow:     K(0.62, 0.64),
        left_wrist:      K(0.46, 0.02),  right_wrist:     K(0.64, 0.82),
        left_hip:        K(0.40, 0.58),  right_hip:       K(0.50, 0.66),
        left_knee:       K(0.14, 0.80),  right_knee:      K(0.70, 0.80),
        left_ankle:      K(0.04, 0.96),  right_ankle:     K(0.84, 0.96),
    };

    const KP_UTKATASANA = {  // Chair (side)
        nose:            K(0.52, 0.20),
        left_shoulder:   K(0.44, 0.32),  right_shoulder:  K(0.56, 0.32),
        left_elbow:      K(0.48, 0.18),  right_elbow:     K(0.60, 0.18),
        left_wrist:      K(0.52, 0.02),  right_wrist:     K(0.64, 0.02),
        left_hip:        K(0.42, 0.60),  right_hip:       K(0.54, 0.60),
        left_knee:       K(0.30, 0.72),  right_knee:      K(0.42, 0.72),
        left_ankle:      K(0.30, 0.96),  right_ankle:     K(0.42, 0.96),
    };

    const KP_PARSVA = {  // Extended Side Angle (side)
        nose:            K(0.38, 0.62),
        left_shoulder:   K(0.34, 0.48),  right_shoulder:  K(0.42, 0.56),
        left_elbow:      K(0.46, 0.30),  right_elbow:     K(0.50, 0.68),
        left_wrist:      K(0.58, 0.10),  right_wrist:     K(0.60, 0.80),
        left_hip:        K(0.32, 0.68),  right_hip:       K(0.42, 0.64),
        left_knee:       K(0.18, 0.86),  right_knee:      K(0.68, 0.78),
        left_ankle:      K(0.04, 0.96),  right_ankle:     K(0.88, 0.96),
    };

    const KP_BRIDGE = {  // Bridge (side — lying on back, hips lifted)
        nose:            K(0.14, 0.80),
        left_shoulder:   K(0.20, 0.78),  right_shoulder:  K(0.22, 0.80),
        left_elbow:      K(0.26, 0.84),  right_elbow:     K(0.28, 0.86),
        left_wrist:      K(0.34, 0.88),  right_wrist:     K(0.36, 0.90),
        left_hip:        K(0.60, 0.48),  right_hip:       K(0.62, 0.50),
        left_knee:       K(0.78, 0.60),  right_knee:      K(0.80, 0.62),
        left_ankle:      K(0.86, 0.88),  right_ankle:     K(0.88, 0.90),
    };

    const KP_VIR3 = {  // Warrior III (side — balancing on one leg, body horizontal)
        nose:            K(0.14, 0.46),
        left_shoulder:   K(0.26, 0.50),  right_shoulder:  K(0.28, 0.52),
        left_elbow:      K(0.10, 0.50),  right_elbow:     K(0.12, 0.52),
        left_wrist:      K(0.00, 0.50),  right_wrist:     K(0.02, 0.52),
        left_hip:        K(0.54, 0.54),  right_hip:       K(0.56, 0.56),
        left_knee:       K(0.74, 0.56),  right_knee:      K(0.60, 0.72),
        left_ankle:      K(0.94, 0.56),  right_ankle:     K(0.66, 0.96),
    };

    const KP_HALFMOON = {  // Ardha Chandrasana (side — balancing on one leg + one hand)
        nose:            K(0.48, 0.28),
        left_shoulder:   K(0.38, 0.34),  right_shoulder:  K(0.46, 0.42),
        left_elbow:      K(0.38, 0.18),  right_elbow:     K(0.48, 0.62),
        left_wrist:      K(0.38, 0.02),  right_wrist:     K(0.50, 0.80),
        left_hip:        K(0.42, 0.52),  right_hip:       K(0.50, 0.58),
        left_knee:       K(0.70, 0.38),  right_knee:      K(0.58, 0.74),
        left_ankle:      K(0.96, 0.24),  right_ankle:     K(0.64, 0.96),
    };

    const KP_DANCER = {  // Natarajasana (side — dancer)
        nose:            K(0.40, 0.18),
        left_shoulder:   K(0.38, 0.30),  right_shoulder:  K(0.46, 0.30),
        left_elbow:      K(0.22, 0.26),  right_elbow:     K(0.54, 0.38),
        left_wrist:      K(0.04, 0.22),  right_wrist:     K(0.70, 0.38),
        left_hip:        K(0.46, 0.58),  right_hip:       K(0.50, 0.58),
        left_knee:       K(0.48, 0.78),  right_knee:      K(0.78, 0.36),
        left_ankle:      K(0.50, 0.98),  right_ankle:     K(0.92, 0.16),
    };

    // ─────────────────────────────────────────────────────────────
    // LIBRARY (20 POSES) — each includes richer rules + reference keypoints
    // ─────────────────────────────────────────────────────────────
    const ASANA_LIBRARY = [
        // ─── BEGINNER (10) ─────────────────────────────────────
        {
            name: 'Tadasana', imageKey: 'tadasana', imagePath: '/assets/poses/tadasana.jpg',
            sanskrit: 'Mountain Pose',
            category: 'Beginner',
            emoji: '⛰️',
            view: 'front',
            benefits: 'The foundation of every standing asana. Builds postural awareness, grounding, and mental clarity.',
            precaution: 'Avoid with low blood pressure or dizziness. Keep eyes open if balance is new.',
            targeted: 'Spine, legs, core',
            steps: [
                'Stand with feet hip-width apart, toes forward.',
                'Distribute weight evenly across both feet.',
                'Engage thighs, lengthen tailbone down.',
                'Roll shoulders back and down; arms by your sides.',
                'Lift crown of head; soften the jaw.',
            ],
            referenceKeypoints: KP_TADASANA,
            rules: [
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 0.25, maxFrac: 0.75, message: 'Feet hip-width apart', priority: 2 },
                { type: 'alignY', joints: ['left_ankle', 'right_ankle'], tolFrac: 0.08, message: 'Weight even on both feet', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [158, 202], message: 'Engage left quadriceps, straighten knee', priority: 1 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [158, 202], message: 'Engage right quadriceps, straighten knee', priority: 1 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.14, message: 'Level your hips', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.14, message: 'Relax shoulders, keep them level', priority: 2 },
                { type: 'distance', joints: ['left_shoulder', 'right_shoulder'], minFrac: 0.7, maxFrac: 1.4, message: 'Broaden the collarbones', priority: 3 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.24, message: 'Crown of head over the body', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, lengthen the spine', priority: 2 },
                { type: 'lower', joints: ['left_wrist', 'left_hip'], bufferFrac: 0.1, message: 'Let the arms rest by your sides', priority: 3 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.1, message: 'Let the arms rest by your sides', priority: 3 },
                { type: 'symmetric', joints: ['left_hip', 'left_knee', 'left_ankle', 'right_hip', 'right_knee', 'right_ankle'], tolDeg: 14, message: 'Stand evenly on both legs', priority: 2 },
            ],
        },
        {
            name: 'Urdhva Hastasana', imageKey: 'urdhva', imagePath: '/assets/poses/urdhva.png',
            sanskrit: 'Upward Salute',
            category: 'Beginner',
            emoji: '🙌',
            view: 'front',
            benefits: 'Opens the chest and side body. A simple lengthening that resets posture and breathing.',
            precaution: 'Drop arms slightly if shoulders strain; avoid if you have a shoulder impingement.',
            targeted: 'Shoulders, side body, spine',
            steps: [
                'Start in Tadasana.',
                'Inhale, sweep arms out and up.',
                'Reach fingertips toward the ceiling.',
                'Keep shoulders away from ears.',
                'Lengthen tail down as you lift the chest.',
            ],
            referenceKeypoints: KP_URDHVA,
            rules: [
                { type: 'higher', joints: ['left_wrist', 'nose'], bufferFrac: 0.4, message: 'Reach the left hand high above your head', priority: 1 },
                { type: 'higher', joints: ['right_wrist', 'nose'], bufferFrac: 0.4, message: 'Reach the right hand high above your head', priority: 1 },
                { type: 'higher', joints: ['left_elbow', 'left_shoulder'], bufferFrac: 0.1, message: 'Lift the left elbow above the shoulder', priority: 2 },
                { type: 'higher', joints: ['right_elbow', 'right_shoulder'], bufferFrac: 0.1, message: 'Lift the right elbow above the shoulder', priority: 2 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 200], message: 'Straighten the left arm, energy through fingertips', priority: 2 },
                { type: 'angle', joints: ['right_shoulder', 'right_elbow', 'right_wrist'], range: [150, 200], message: 'Straighten the right arm, energy through fingertips', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Keep the left leg strong and straight', priority: 2 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Keep the right leg strong and straight', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.1, message: 'Level your hips', priority: 2 },
                { type: 'distance', joints: ['left_wrist', 'right_wrist'], minFrac: 0.2, maxFrac: 1.2, message: 'Arms can be shoulder-width or touching overhead', priority: 3 },
                { type: 'symmetric', joints: ['left_shoulder', 'left_elbow', 'left_wrist', 'right_shoulder', 'right_elbow', 'right_wrist'], tolDeg: 18, message: 'Reach evenly with both arms', priority: 3 },
            ],
        },
        {
            name: 'Anjali Mudra', imageKey: 'anjali', imagePath: '/assets/poses/anjali.png',
            sanskrit: 'Prayer at Heart',
            category: 'Beginner',
            emoji: '🙏',
            view: 'front',
            benefits: 'A centering gesture that quiets the mind and opens the chest. A common bookend to practice.',
            precaution: 'Keep the spine tall; do not hunch the shoulders.',
            targeted: 'Wrists, chest, breath',
            steps: [
                'Stand or sit tall.',
                'Bring palms together in front of the heart.',
                'Press the bases of the palms and thumbs against the sternum.',
                'Keep elbows wide and collarbones broad.',
                'Soften the gaze; take three slow breaths.',
            ],
            referenceKeypoints: KP_ANJALI,
            rules: [
                { type: 'distance', joints: ['left_wrist', 'right_wrist'], minFrac: 0, maxFrac: 0.22, message: 'Press palms firmly together at the heart', priority: 1 },
                { type: 'alignY', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.08, message: 'Keep both wrists at the same height', priority: 1 },
                { type: 'distance', joints: ['left_elbow', 'right_elbow'], minFrac: 0.6, maxFrac: 1.4, message: 'Widen the elbows to open the chest', priority: 2 },
                { type: 'alignY', joints: ['left_elbow', 'right_elbow'], tolFrac: 0.1, message: 'Level the elbows', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Relax and level the shoulders', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest; do not hunch', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Stand tall, strong legs', priority: 3 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Stand tall, strong legs', priority: 3 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.18, message: 'Crown of head over the body', priority: 2 },
            ],
        },
        {
            name: 'Vrikshasana', imageKey: 'vrikshasana', imagePath: '/assets/poses/vrikshasana.png',
            sanskrit: 'Tree Pose',
            category: 'Beginner',
            emoji: '🌳',
            view: 'front',
            benefits: 'Trains balance, focus, and ankle strength. Opens the inner thighs and teaches calm concentration.',
            precaution: 'Never press the foot against the knee. Use a wall for support if needed.',
            targeted: 'Legs, hips, balance',
            steps: [
                'Stand in Tadasana.',
                'Shift weight onto the left leg.',
                'Place right sole on left inner calf or thigh (not the knee).',
                'Press the foot into the leg and the leg into the foot.',
                'Hands at heart or reach them up.',
            ],
            referenceKeypoints: KP_VRIKSHASANA,
            rules: [
                { type: 'angle', joints: ['standing_hip', 'standing_knee', 'standing_ankle'], range: [158, 202], message: 'Standing leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['raised_ankle', 'standing_knee'], bufferFrac: 0.05, message: 'Lift the raised foot higher onto the inner leg', priority: 1 },
                { type: 'higher', joints: ['right_knee', 'right_hip'], bufferFrac: -0.05, message: 'Open the bent knee out to the side', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Shoulders level, do not lean', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.12, message: 'Level your hips', priority: 2 },
                { type: 'alignX', joints: ['nose', 'standing_ankle'], tolFrac: 0.25, message: 'Stack crown over the standing foot', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, lengthen the spine', priority: 2 },
            ],
        },
        {
            name: 'Uttanasana', imageKey: 'uttanasana', imagePath: '/assets/poses/uttanasana.png',
            sanskrit: 'Standing Forward Fold',
            category: 'Beginner',
            emoji: '🙇',
            view: 'side',
            benefits: 'Lengthens the hamstrings and spine. Calms the nervous system and releases the neck.',
            precaution: 'Bend the knees generously if hamstrings are tight. Avoid with disc issues.',
            targeted: 'Hamstrings, back, neck',
            steps: [
                'Stand with feet hip-width apart.',
                'Exhale and hinge forward from the hips.',
                'Let the head hang heavy; micro-bend the knees if needed.',
                'Hands to the mat, shins, or grab opposite elbows.',
                'Relax the jaw and breathe into the back body.',
            ],
            referenceKeypoints: KP_UTTANASANA,
            rules: [
                { type: 'lower', joints: ['nose', 'left_hip'], bufferFrac: 0.05, message: 'Fold deeper from the hips; let the head hang', priority: 1 },
                { type: 'lower', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.05, message: 'Hinge from the hips, release the spine down', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Lengthen the legs; a small bend is fine', priority: 2 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [150, 200], message: 'Lengthen the legs; a small bend is fine', priority: 2 },
                { type: 'lower', joints: ['left_wrist', 'left_knee'], bufferFrac: -0.05, message: 'Hands toward the shins or mat', priority: 2 },
                { type: 'alignX', joints: ['left_shoulder', 'left_ankle'], tolFrac: 0.3, message: 'Stack shoulders over the feet, not behind', priority: 2 },
            ],
        },
        {
            name: 'Sukhasana', imageKey: 'sukhasana', imagePath: '/assets/poses/sukhasana.png',
            sanskrit: 'Easy Seated Pose',
            category: 'Beginner',
            emoji: '🧘',
            view: 'front',
            benefits: 'A foundational seat for breath work and meditation. Opens the hips and tall spine.',
            precaution: 'Sit on a cushion or block if the knees lift above the hips.',
            targeted: 'Hips, spine, ankles',
            steps: [
                'Sit with the legs crossed at the shins.',
                'Root the sit bones evenly into the floor.',
                'Stack the shoulders over the hips.',
                'Soften the hands onto the knees.',
                'Lengthen the crown of the head upward.',
            ],
            referenceKeypoints: KP_SUKHASANA,
            rules: [
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.3, message: 'Lift the spine tall — shoulders above hips', priority: 1 },
                { type: 'alignX', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.1, message: 'Stack the shoulders over the hips', priority: 1 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.15, message: 'Sit evenly on both sit bones', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.12, message: 'Level the shoulders', priority: 2 },
                { type: 'lower', joints: ['left_knee', 'left_hip'], bufferFrac: -0.02, message: 'Let the knees settle toward the floor', priority: 3 },
                { type: 'lower', joints: ['right_knee', 'right_hip'], bufferFrac: -0.02, message: 'Let the knees settle toward the floor', priority: 3 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.15, message: 'Crown of head over the body', priority: 2 },
            ],
        },
        {
            name: 'Dandasana', imageKey: 'dandasana', imagePath: '/assets/poses/dandasana.png',
            sanskrit: 'Staff Pose',
            category: 'Beginner',
            emoji: '📏',
            view: 'side',
            benefits: 'The seated equivalent of Tadasana. Teaches active legs and an upright spine.',
            precaution: 'Sit on a folded blanket if the pelvis tips backward.',
            targeted: 'Spine, core, hamstrings',
            steps: [
                'Sit with legs extended straight in front.',
                'Flex the feet; engage thighs.',
                'Place hands beside the hips, fingers forward.',
                'Lift the chest and lengthen the crown up.',
                'Press sit bones into the floor.',
            ],
            referenceKeypoints: KP_DANDASANA,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Straighten the legs, engage the thighs', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.3, message: 'Lengthen the spine up, shoulders above hips', priority: 1 },
                { type: 'alignX', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.1, message: 'Stack the shoulders over the hips', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Keep shoulders level', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'left_knee'], tolFrac: 0.1, message: 'Lengthen legs along the floor', priority: 2 },
                { type: 'alignY', joints: ['left_knee', 'left_ankle'], tolFrac: 0.1, message: 'Keep the feet flexed, legs strong', priority: 2 },
                { type: 'alignX', joints: ['nose', 'left_shoulder'], tolFrac: 0.2, message: 'Gaze forward, neck in line with spine', priority: 3 },
            ],
        },
        {
            name: 'Baddha Konasana', imageKey: 'baddha', imagePath: '/assets/poses/baddha.png',
            sanskrit: 'Bound Angle Pose',
            category: 'Beginner',
            emoji: '🦋',
            view: 'front',
            benefits: 'Opens the inner thighs and hips. Stimulates abdominal organs and improves circulation.',
            precaution: 'Place blocks under the knees if they are high. Avoid with recent knee injury.',
            targeted: 'Hips, groin, pelvis',
            steps: [
                'Sit tall, bend knees, bring soles of feet together.',
                'Hold the feet or ankles.',
                'Draw heels gently toward the pelvis.',
                'Let the knees melt down without forcing.',
                'Lengthen the crown up.',
            ],
            referenceKeypoints: KP_BADDHA,
            rules: [
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 0, maxFrac: 0.28, message: 'Bring the heels closer together', priority: 2 },
                { type: 'distance', joints: ['left_knee', 'right_knee'], minFrac: 0.9, maxFrac: 2.6, message: 'Let the knees widen out to the sides', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.25, message: 'Lift the chest, lengthen the spine', priority: 1 },
                { type: 'alignY', joints: ['left_knee', 'right_knee'], tolFrac: 0.15, message: 'Let both knees drop evenly', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.1, message: 'Sit evenly on both sit bones', priority: 2 },
                { type: 'symmetric', joints: ['left_hip', 'left_knee', 'left_ankle', 'right_hip', 'right_knee', 'right_ankle'], tolDeg: 20, message: 'Open the hips evenly on both sides', priority: 3 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.15, message: 'Keep the crown centred over the hips', priority: 3 },
            ],
        },
        {
            name: 'Paschimottanasana', imageKey: 'paschimottanasana', imagePath: '/assets/poses/paschimottanasana.png',
            sanskrit: 'Seated Forward Fold',
            category: 'Beginner',
            emoji: '🧎',
            view: 'side',
            benefits: 'Stretches the entire back body from heels to crown. Soothes the mind and eases tension.',
            precaution: 'Bend knees if the low back rounds sharply. Avoid with disc injury.',
            targeted: 'Hamstrings, spine, calves',
            steps: [
                'Begin in Dandasana.',
                'Inhale, lengthen the spine upward.',
                'Exhale, hinge forward from the hips.',
                'Reach for shins, ankles, or soles.',
                'Let the head hang; keep the neck soft.',
            ],
            referenceKeypoints: KP_PASCHIMO,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Keep the legs long; a small bend is fine', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'left_knee'], tolFrac: 0.35, message: 'Fold deeper over the legs, leading with the chest', priority: 1 },
                { type: 'alignY', joints: ['nose', 'left_knee'], tolFrac: 0.4, message: 'Bring the forehead toward the shins', priority: 2 },
                { type: 'lower', joints: ['left_wrist', 'left_knee'], bufferFrac: 0, message: 'Reach the hands toward the feet', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'left_knee'], tolFrac: 0.12, message: 'Legs extended and pressing into the floor', priority: 2 },
            ],
        },
        {
            name: 'Balasana', imageKey: 'balasana', imagePath: '/assets/poses/balasana.png',
            sanskrit: 'Child\u2019s Pose',
            category: 'Beginner',
            emoji: '🧸',
            view: 'side',
            benefits: 'A resting pose between stronger asanas. Releases the back and quiets the mind.',
            precaution: 'Place a blanket between calves and thighs if knees are sensitive.',
            targeted: 'Low back, hips, knees',
            steps: [
                'Kneel with big toes touching, knees wide.',
                'Sit hips back onto the heels.',
                'Walk hands forward and rest the forehead down.',
                'Let arms extend or relax by the sides.',
                'Soften the breath into the back body.',
            ],
            referenceKeypoints: KP_BALASANA,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [20, 90], message: 'Sink the hips back toward the heels', priority: 1 },
                { type: 'lower', joints: ['left_shoulder', 'left_knee'], bufferFrac: -0.05, message: 'Relax the torso over the thighs', priority: 1 },
                { type: 'lower', joints: ['nose', 'left_shoulder'], bufferFrac: 0.05, message: 'Rest the forehead down; release the neck', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: -0.05, message: 'Arms extend forward or rest by the sides', priority: 3 },
                { type: 'alignY', joints: ['left_hip', 'left_ankle'], tolFrac: 0.25, message: 'Bring the hips down toward the heels', priority: 2 },
            ],
        },

        // ─── INTERMEDIATE (7) ─────────────────────────────────
        {
            name: 'Adho Mukha Svanasana', imageKey: 'adhomukha', imagePath: '/assets/poses/adhomukha.png',
            sanskrit: 'Downward-Facing Dog',
            category: 'Intermediate',
            emoji: '🐕',
            view: 'side',
            benefits: 'Full-body tonic. Stretches the back line, strengthens arms, and energises.',
            precaution: 'Avoid with carpal tunnel or uncontrolled high blood pressure.',
            targeted: 'Shoulders, back, hamstrings',
            steps: [
                'Start on hands and knees, wrists under shoulders.',
                'Tuck the toes and lift the hips up and back.',
                'Press hands firmly; straighten the arms.',
                'Soften the knees if the low back rounds.',
                'Reach the heels toward the floor without forcing.',
            ],
            referenceKeypoints: KP_DOWNDOG,
            rules: [
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [160, 200], message: 'Straighten the arms, press through the palms', priority: 1 },
                { type: 'angle', joints: ['right_shoulder', 'right_elbow', 'right_wrist'], range: [160, 200], message: 'Straighten the arms, press through the palms', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Lengthen through the legs; a small bend is fine', priority: 2 },
                { type: 'higher', joints: ['left_hip', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the hips higher, pike the shape', priority: 1 },
                { type: 'higher', joints: ['left_hip', 'left_knee'], bufferFrac: 0.2, message: 'Send the hips up and back', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'left_wrist'], tolFrac: 0.4, message: 'Press the arms long, biceps by the ears', priority: 2 },
                { type: 'symmetric', joints: ['left_shoulder', 'left_elbow', 'left_wrist', 'right_shoulder', 'right_elbow', 'right_wrist'], tolDeg: 12, message: 'Press evenly through both hands', priority: 3 },
            ],
        },
        {
            name: 'Virabhadrasana I', imageKey: 'warrior1', imagePath: '/assets/poses/warrior1.png',
            sanskrit: 'Warrior I',
            category: 'Intermediate',
            emoji: '⚔️',
            view: 'side',
            benefits: 'Strengthens legs and core. Opens the chest and hip flexors.',
            precaution: 'Keep the front knee tracking over the ankle. Avoid with knee pain.',
            targeted: 'Legs, hips, chest',
            steps: [
                'Step the right foot forward into a long lunge.',
                'Turn the back foot out 45 degrees.',
                'Bend the front knee over the ankle.',
                'Square the hips forward; lift the chest.',
                'Reach the arms up alongside the ears.',
            ],
            referenceKeypoints: KP_VIR1,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [85, 115], message: 'Bend the front knee toward 90 degrees', priority: 1 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [150, 200], message: 'Straighten and ground the back leg', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the arms overhead, alongside the ears', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: 0.3, message: 'Reach both arms up evenly', priority: 2 },
                { type: 'alignX', joints: ['forward_knee', 'forward_ankle'], tolFrac: 0.15, message: 'Front knee tracks over the front ankle', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, open the heart', priority: 2 },
                { type: 'symmetric', joints: ['left_shoulder', 'left_elbow', 'left_wrist', 'right_shoulder', 'right_elbow', 'right_wrist'], tolDeg: 18, message: 'Arms reach up evenly', priority: 3 },
            ],
        },
        {
            name: 'Virabhadrasana II', imageKey: 'warrior2', imagePath: '/assets/poses/warrior2.png',
            sanskrit: 'Warrior II',
            category: 'Intermediate',
            emoji: '🛡️',
            view: 'front',
            benefits: 'Builds stamina and focus. Opens the hips and strengthens the legs.',
            precaution: 'Never let the front knee drift past the toes.',
            targeted: 'Legs, hips, shoulders',
            steps: [
                'From a wide stance, turn the right foot out 90 degrees.',
                'Back foot slightly angled in.',
                'Bend the front knee over the ankle.',
                'Extend arms wide at shoulder height.',
                'Gaze over the front middle finger.',
            ],
            referenceKeypoints: KP_VIR2,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [85, 115], message: 'Front knee bends to 90, tracks over the ankle', priority: 1 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'horizontalSpan', joints: ['left_wrist', 'right_wrist'], minDx: 1.0, maxDy: 0.2, message: 'Arms out wide, parallel to the floor', priority: 2 },
                { type: 'alignY', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.12, message: 'Lift both arms to shoulder height', priority: 2 },
                { type: 'alignY', joints: ['left_wrist', 'left_shoulder'], tolFrac: 0.15, message: 'Left arm at shoulder height', priority: 2 },
                { type: 'alignY', joints: ['right_wrist', 'right_shoulder'], tolFrac: 0.15, message: 'Right arm at shoulder height', priority: 2 },
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 1.6, maxFrac: 3.5, message: 'Widen the stance, long lunge', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.12, message: 'Level the hips', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Torso upright, chest lifted', priority: 2 },
            ],
        },
        {
            name: 'Utthita Trikonasana', imageKey: 'trikonasana', imagePath: '/assets/poses/trikonasana.png',
            sanskrit: 'Extended Triangle',
            category: 'Intermediate',
            emoji: '📐',
            view: 'side',
            benefits: 'Stretches the side body, hamstrings, and hips. Tones the legs and core.',
            precaution: 'Avoid with neck injury. Place a block under the lower hand if needed.',
            targeted: 'Side body, legs, hips',
            steps: [
                'From a wide stance, turn the right foot out.',
                'Keep both legs straight.',
                'Extend the torso over the front leg.',
                'Lower right hand to shin, block, or floor.',
                'Stack the left arm straight up.',
            ],
            referenceKeypoints: KP_TRIKON,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [155, 200], message: 'Front leg strong and straight', priority: 1 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.2, message: 'Stack the top arm directly above the bottom', priority: 2 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm toward the ceiling', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.05, message: 'Lower the bottom hand to shin or block', priority: 2 },
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 1.6, maxFrac: 3.5, message: 'Widen the stance for the triangle shape', priority: 2 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 200], message: 'Extend the top arm fully', priority: 3 },
            ],
        },
        {
            name: 'Utkatasana', imageKey: 'utkatasana', imagePath: '/assets/poses/utkatasana.png',
            sanskrit: 'Chair Pose',
            category: 'Intermediate',
            emoji: '🪑',
            view: 'side',
            benefits: 'Builds heat and strengthens the entire lower body. Engages the core.',
            precaution: 'Ease up if knees or low back feel pinched.',
            targeted: 'Thighs, glutes, core',
            steps: [
                'Stand in Tadasana.',
                'Bend the knees as if sitting in an invisible chair.',
                'Keep the knees tracking over the toes.',
                'Lift the chest; reach arms up alongside the ears.',
                'Draw the low belly in and breathe.',
            ],
            referenceKeypoints: KP_UTKATASANA,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [90, 140], message: 'Sit lower into the chair shape', priority: 1 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [90, 140], message: 'Sit lower into the chair shape', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the arms up alongside the ears', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: 0.3, message: 'Reach both hands up evenly', priority: 2 },
                { type: 'alignX', joints: ['left_knee', 'left_ankle'], tolFrac: 0.2, message: 'Knees tracking over ankles, not past toes', priority: 1 },
                { type: 'symmetric', joints: ['left_hip', 'left_knee', 'left_ankle', 'right_hip', 'right_knee', 'right_ankle'], tolDeg: 10, message: 'Knees bent evenly', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.4, message: 'Lift the chest, lengthen the spine', priority: 2 },
            ],
        },
        {
            name: 'Utthita Parsvakonasana', imageKey: 'parsvakonasana', imagePath: '/assets/poses/parsvakonasana.png',
            sanskrit: 'Extended Side Angle',
            category: 'Intermediate',
            emoji: '📏',
            view: 'side',
            benefits: 'Strengthens the legs and opens the side body from heel to fingertips.',
            precaution: 'Use a block under the lower hand if the torso collapses.',
            targeted: 'Legs, side body, shoulders',
            steps: [
                'From Warrior II, lower the front forearm to the thigh.',
                'Or lower the front hand to the floor outside the foot.',
                'Reach the top arm over the ear.',
                'Create one long line from back heel to top fingertips.',
                'Open the chest toward the ceiling.',
            ],
            referenceKeypoints: KP_PARSVA,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [85, 115], message: 'Front knee bent to 90 degrees', priority: 1 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm up and over the ear', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.3, message: 'Lengthen the side body from hip to fingertips', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0, message: 'Lower the front hand to forearm, block, or floor', priority: 2 },
                { type: 'alignX', joints: ['forward_knee', 'forward_ankle'], tolFrac: 0.15, message: 'Front knee tracks over the ankle', priority: 1 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 200], message: 'Top arm straight over the ear', priority: 3 },
            ],
        },
        {
            name: 'Setu Bandhasana', imageKey: 'setubandhasana', imagePath: '/assets/poses/setubandhasana.png',
            sanskrit: 'Bridge Pose',
            category: 'Intermediate',
            emoji: '🌉',
            view: 'side',
            benefits: 'Opens the chest and hip flexors. Strengthens the back body.',
            precaution: 'Avoid with neck injury. Keep knees parallel.',
            targeted: 'Glutes, chest, spine',
            steps: [
                'Lie on your back; bend knees, feet hip-width, heels near the sit bones.',
                'Press into the feet and lift the hips.',
                'Clasp hands under the back if comfortable.',
                'Keep the chin slightly away from the chest.',
                'Breathe into the chest.',
            ],
            referenceKeypoints: KP_BRIDGE,
            rules: [
                { type: 'higher', joints: ['left_hip', 'left_shoulder'], bufferFrac: 0.15, message: 'Lift the hips higher toward the ceiling', priority: 1 },
                { type: 'higher', joints: ['left_hip', 'left_knee'], bufferFrac: 0.05, message: 'Drive the hips up, not out', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [70, 120], message: 'Stack knees over ankles', priority: 2 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [70, 120], message: 'Stack knees over ankles', priority: 2 },
                { type: 'distance', joints: ['left_knee', 'right_knee'], minFrac: 0.3, maxFrac: 1.1, message: 'Keep knees hip-width apart, parallel', priority: 2 },
                { type: 'alignY', joints: ['left_ankle', 'right_ankle'], tolFrac: 0.1, message: 'Feet grounded evenly', priority: 3 },
            ],
        },

        // ─── ADVANCED (3) ──────────────────────────────────────
        {
            name: 'Virabhadrasana III', imageKey: 'warrior3', imagePath: '/assets/poses/warrior3.png',
            sanskrit: 'Warrior III',
            category: 'Advanced',
            emoji: '🏹',
            view: 'side',
            benefits: 'Challenges balance and strengthens the whole posterior chain.',
            precaution: 'Practice near a wall if balance is new. Avoid with sciatica flare-ups.',
            targeted: 'Glutes, hamstrings, core',
            steps: [
                'From a high lunge, shift weight into the front leg.',
                'Lean the torso forward as the back leg lifts.',
                'Torso, back leg, and arms reach parallel to the floor.',
                'Flex the back foot; engage the core.',
                'Keep the gaze soft on the floor.',
            ],
            referenceKeypoints: KP_VIR3,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [160, 200], message: 'Fully straighten the standing leg', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.2, message: 'Lift the back leg parallel to the floor', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.2, message: 'Bring the torso parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: -0.05, message: 'Reach the arms forward at shoulder height', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: -0.05, message: 'Reach the arms forward at shoulder height', priority: 2 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [160, 200], message: 'Extend the back leg fully, flex the foot', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.15, message: 'Keep the hips level, do not open the back hip', priority: 2 },
            ],
        },
        {
            name: 'Ardha Chandrasana', imageKey: 'ardhachandra', imagePath: '/assets/poses/ardhachandra.png',
            sanskrit: 'Half Moon Pose',
            category: 'Advanced',
            emoji: '🌓',
            view: 'side',
            benefits: 'Builds balance, strengthens legs, and opens the side body and chest.',
            precaution: 'Use a block under the bottom hand for support.',
            targeted: 'Legs, hips, core',
            steps: [
                'From Trikonasana, bend the front knee and step the back foot in.',
                'Shift weight into the front foot; hand to the floor or a block.',
                'Lift the back leg parallel to the floor; flex the foot.',
                'Stack the top hip over the bottom.',
                'Raise the top arm skyward.',
            ],
            referenceKeypoints: KP_HALFMOON,
            rules: [
                { type: 'angle', joints: ['forward_hip', 'forward_knee', 'forward_ankle'], range: [160, 200], message: 'Straighten the standing leg fully', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.3, message: 'Float the top leg parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Stack the top arm straight up', priority: 2 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.3, message: 'Line the top arm above the bottom arm', priority: 2 },
                { type: 'angle', joints: ['back_hip', 'back_knee', 'back_ankle'], range: [160, 200], message: 'Extend the lifted leg, flex the foot', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.1, message: 'Ground the bottom hand for support', priority: 2 },
            ],
        },
        {
            name: 'Natarajasana', imageKey: 'natarajasana', imagePath: '/assets/poses/natarajasana.png',
            sanskrit: 'Dancer Pose',
            category: 'Advanced',
            emoji: '💃',
            view: 'side',
            benefits: 'Elegant balance that opens the chest, shoulders, and front body.',
            precaution: 'Warm up the hamstrings and quads. Use a strap if you cannot reach the foot.',
            targeted: 'Quads, hip flexors, shoulders',
            steps: [
                'Stand in Tadasana. Shift weight into the left leg.',
                'Bend the right knee and catch the inside of the foot.',
                'Reach the left arm forward and up.',
                'Kick the right foot back into the hand; hinge slightly forward.',
                'Find a steady gaze point.',
            ],
            referenceKeypoints: KP_DANCER,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Standing leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['right_ankle', 'right_hip'], bufferFrac: 0.1, message: 'Kick the back foot high behind you', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.15, message: 'Reach the front arm forward and up', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: -0.1, message: 'Catch the foot; elbow points up', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.4, message: 'Lift the chest, do not collapse forward', priority: 2 },
            ],
        },
    ];

    window.ASANA_LIBRARY = ASANA_LIBRARY;
    window.asanaData = ASANA_LIBRARY;
    window.PoseEngine = PoseEngine;
    window.PoseImage = PoseImage;
})();
