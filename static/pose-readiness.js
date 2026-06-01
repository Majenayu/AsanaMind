/**
 * Sunday · AsanMinds — Pose Readiness Gate
 *
 * Per-frame check that runs BEFORE the rule engine scores the user, with
 * one job: stop a half-visible body from earning a 100% score.
 *
 * Why this exists:
 *   On mobile (portrait, phone propped 1-2m back), MoveNet still returns
 *   17 keypoints even when the user's head or feet are clipped out of
 *   frame — but the missing points have low confidence (0.1-0.3) and
 *   guessed coordinates. The rule engine doesn't know any of that and
 *   happily scores rules using fabricated joint positions, which is how
 *   half-cropped torsos sometimes pass a 90% Tadasana.
 *
 * What this exports:
 *   PoseReadiness.check(keypoints, poseName, video) → {
 *     state:           'READY' | 'PARTIAL' | 'OFF_FRAME',
 *     visibilityScore: 0..100  (raw, per-frame)
 *     stableVisibility:0..100  (last 3-5 frames averaged, used for cap)
 *     missing:         ['leftAnkle', ...]  // human-readable parts
 *     capMultiplier:   0..1   (multiply form score by this)
 *     isMobile:        boolean
 *   }
 *
 *   PoseReadiness.applyCap(formScore, readiness) → capped 0..100
 *
 *   PoseReadiness.requiredFor(poseName) → array of MoveNet keypoint names
 *
 * Tunables live at the top of this file. The rest of the app is allowed
 * to read them via PoseReadiness.config but should not mutate them.
 */
(function (root) {
    'use strict';

    // ─── Config ──────────────────────────────────────────────────────
    const CONFIG = {
        // Per-frame keypoint must clear this confidence to count as "detected".
        // MoveNet typical: legitimate joints 0.5-0.95, hallucinated 0.1-0.3.
        // 0.35 strikes the balance — excludes hallucinated points but
        // accepts marginal-but-real detections that 0.4 was rejecting too
        // often, which was preventing the course timer from starting on
        // real users (tester report: "timer doesn't start").
        DETECT_THRESHOLD: 0.35,

        // Frame-margin box, normalised 0..1. Mobile gets a looser bottom edge
        // because phones in portrait crop the toes more than desktop webcams.
        DESKTOP_MARGINS: { left: 0.05, right: 0.95, top: 0.05, bottom: 0.95 },
        MOBILE_MARGINS:  { left: 0.03, right: 0.97, top: 0.03, bottom: 0.98 },

        // Stability buffer length (frames). Mobile detection jitters more, so
        // a small buffer trades 100-300ms of latency for fewer flickers.
        DESKTOP_STABILITY: 3,
        MOBILE_STABILITY: 5,

        // Stepped cap curve. visibilityScore is the y-axis (0..100), the
        // multiplier is what the form score is multiplied by. Scores below
        // 50% visibility hard-zero so the timer cannot advance.
        CAP_CURVE: [
            { vis: 100, mult: 1.00 },
            { vis:  95, mult: 0.95 },
            { vis:  90, mult: 0.85 },
            { vis:  75, mult: 0.60 },
            { vis:  50, mult: 0.30 },
            { vis:   0, mult: 0.00 },
        ],

        // State thresholds. READY needs the body reliably visible — but not
        // so strict that one model-jitter frame on a real camera drops it.
        // 80% means "8 out of 9 required keypoints visible" which is what
        // a properly-framed user actually achieves; 95% was hitting jitter
        // ceilings on Chrome/Android and preventing the test timer from
        // starting at all (tester regression).
        READY_VISIBILITY: 80,
        OFF_FRAME_VISIBILITY: 40,
        OFF_FRAME_MAX_CONF: 0.2,
    };

    // ─── Per-pose required keypoints ─────────────────────────────────
    // MoveNet COCO-17 keypoint names. Pose-models.js normalises BlazePose
    // output to the same names, so this list works for both detectors.
    const FULL_BODY = [
        'nose',
        'leftShoulder', 'rightShoulder',
        'leftHip',      'rightHip',
        'leftKnee',     'rightKnee',
        'leftAnkle',    'rightAnkle',
    ];
    const SEATED = [
        'nose',
        'leftShoulder', 'rightShoulder',
        'leftHip',      'rightHip',
        'leftKnee',     'rightKnee',
    ];
    const UPPER_BODY = [
        'nose',
        'leftShoulder', 'rightShoulder',
        'leftElbow',    'rightElbow',
        'leftWrist',    'rightWrist',
        'leftHip',      'rightHip',
    ];

    // Map keyed by lowercased pose name. Sanskrit and English variants both
    // accepted because main.html sometimes passes one and sometimes the other.
    const POSE_REQUIREMENTS = {
        // Standing — full body strict
        'tadasana':                            FULL_BODY,
        'mountain pose':                       FULL_BODY,
        'vrikshasana':                         FULL_BODY,
        'tree pose':                           FULL_BODY,
        'utkatasana':                          FULL_BODY,
        'chair pose':                          FULL_BODY,
        'natarajasana':                        FULL_BODY,
        'dancer':                              FULL_BODY,
        'dancer pose':                         FULL_BODY,
        'ardha chandrasana':                   FULL_BODY,
        'half moon':                           FULL_BODY,
        'half moon pose':                      FULL_BODY,

        // Warrior — feet placement matters, every joint required
        'virabhadrasana i':                    FULL_BODY,
        'virabhadrasana ii':                   FULL_BODY,
        'virabhadrasana iii':                  FULL_BODY,
        'warrior i':                           FULL_BODY,
        'warrior ii':                          FULL_BODY,
        'warrior iii':                         FULL_BODY,
        'warrior 1':                           FULL_BODY,
        'warrior 2':                           FULL_BODY,
        'warrior 3':                           FULL_BODY,
        'warrior one':                         FULL_BODY,
        'warrior two':                         FULL_BODY,
        'warrior three':                       FULL_BODY,

        // Triangle / side-angle — ankle alignment is the whole point
        'utthita trikonasana':                 FULL_BODY,
        'triangle':                            FULL_BODY,
        'triangle pose':                       FULL_BODY,
        'utthita parsvakonasana':              FULL_BODY,
        'extended side angle':                 FULL_BODY,
        'side angle':                          FULL_BODY,

        // Bridge — face often hidden looking up at the ceiling, drop nose
        'setu bandhasana':                     FULL_BODY.filter(k => k !== 'nose'),
        'bridge':                              FULL_BODY.filter(k => k !== 'nose'),
        'bridge pose':                         FULL_BODY.filter(k => k !== 'nose'),

        // Down dog — head tucked under, hands on floor; need shoulders, hips,
        // knees, ankles. Wrists usually invisible from a side cam.
        'adho mukha svanasana':                ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],
        'downward dog':                        ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],
        'down dog':                            ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],
        'downward facing dog':                 ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],

        // Forward folds — head dangles, drop nose
        'uttanasana':                          ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],
        'standing forward fold':               ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],
        'rag doll':                            ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee', 'leftAnkle', 'rightAnkle'],

        // Seated — ankles tucked / under thighs, optional
        'sukhasana':                           SEATED,
        'easy pose':                           SEATED,
        'easy seat':                           SEATED,
        'dandasana':                           SEATED.concat(['leftAnkle', 'rightAnkle']), // staff has legs straight, ankles ARE visible
        'staff pose':                          SEATED.concat(['leftAnkle', 'rightAnkle']),
        'baddha konasana':                     SEATED,
        'bound angle':                         SEATED,
        'butterfly':                           SEATED,
        'paschimottanasana':                   SEATED.concat(['leftAnkle', 'rightAnkle']),
        'seated forward fold':                 SEATED.concat(['leftAnkle', 'rightAnkle']),
        'forward fold':                        SEATED.concat(['leftAnkle', 'rightAnkle']),

        // Prayer / upper-body emphasis
        'anjali mudra':                        UPPER_BODY,
        'prayer':                              UPPER_BODY,
        'namaste':                             UPPER_BODY,
        'urdhva hastasana':                    ['leftWrist', 'rightWrist', 'leftElbow', 'rightElbow', 'leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
        'upward salute':                       ['leftWrist', 'rightWrist', 'leftElbow', 'rightElbow', 'leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
        'reach up':                            ['leftWrist', 'rightWrist', 'leftElbow', 'rightElbow', 'leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],

        // Child — folded forward, ankles tucked, drop nose
        'balasana':                            ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
        'child':                               ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
        'child pose':                          ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
        'childs pose':                         ['leftShoulder', 'rightShoulder', 'leftHip', 'rightHip', 'leftKnee', 'rightKnee'],
    };

    function requiredFor(poseName) {
        if (!poseName) return FULL_BODY;
        const key = String(poseName).toLowerCase().trim()
            .replace(/^\s*pose\s*:\s*/, '')
            .replace(/\s*\([^)]*\)\s*$/, '');
        return POSE_REQUIREMENTS[key] || FULL_BODY;
    }

    // ─── Mobile detection (cached on first call) ─────────────────────
    let _isMobile = null;
    function isMobile() {
        if (_isMobile !== null) return _isMobile;
        try {
            _isMobile = (typeof window !== 'undefined') && (
                ('ontouchstart' in window) ||
                (window.innerWidth && window.innerWidth <= 768) ||
                (navigator.userAgent && /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent))
            );
        } catch (_) {
            _isMobile = false;
        }
        return _isMobile;
    }

    // ─── Per-frame core check ────────────────────────────────────────
    // Builds a name->{x,y,score} lookup so we can probe by keypoint name
    // regardless of whether the model returned an array of named or
    // index-keyed keypoints.
    function indexKeypoints(keypoints) {
        const out = {};
        if (!keypoints) return out;
        for (let i = 0; i < keypoints.length; i++) {
            const kp = keypoints[i];
            if (!kp) continue;
            const name = kp.name || kp.partName || null;
            if (name) out[name] = kp;
        }
        return out;
    }

    function frameCheck(keypoints, video, required) {
        const margins = isMobile() ? CONFIG.MOBILE_MARGINS : CONFIG.DESKTOP_MARGINS;
        const w = (video && video.videoWidth)  || 1;
        const h = (video && video.videoHeight) || 1;

        const lookup = indexKeypoints(keypoints);
        const missing = [];
        let detected = 0;
        let inFrame = 0;
        let maxConfidence = 0;

        for (const name of required) {
            const kp = lookup[name];
            if (!kp) { missing.push(name); continue; }
            const conf = kp.score || kp.visibility || 0;
            if (conf > maxConfidence) maxConfidence = conf;

            const passConf = conf >= CONFIG.DETECT_THRESHOLD;
            // MoveNet returns absolute pixel coords; BlazePose normalised 0..1.
            // Detect which by checking magnitude.
            const xn = kp.x > 1.5 ? kp.x / w : kp.x;
            const yn = kp.y > 1.5 ? kp.y / h : kp.y;
            const passFrame = xn >= margins.left && xn <= margins.right &&
                              yn >= margins.top  && yn <= margins.bottom;

            if (passConf) detected++;
            if (passConf && passFrame) inFrame++;
            if (!passConf || !passFrame) missing.push(name);
        }

        // Also check max confidence across ALL keypoints (not just required)
        // so we can detect "no body in frame at all" reliably.
        for (const k in lookup) {
            const c = lookup[k].score || lookup[k].visibility || 0;
            if (c > maxConfidence) maxConfidence = c;
        }

        const total = required.length || 1;
        const detectedRatio = detected / total;
        const inFrameRatio  = inFrame  / total;
        // Visibility = the WORST of the two ratios (both must be high).
        const visibilityScore = Math.round(Math.min(detectedRatio, inFrameRatio) * 100);

        return { visibilityScore, missing, maxConfidence };
    }

    // ─── Stability buffer ────────────────────────────────────────────
    // Keyed by pose name so switching poses doesn't carry a stale buffer.
    const _stability = { poseName: null, samples: [] };

    function pushStability(poseName, visibility) {
        if (_stability.poseName !== poseName) {
            _stability.poseName = poseName;
            _stability.samples = [];
        }
        const cap = isMobile() ? CONFIG.MOBILE_STABILITY : CONFIG.DESKTOP_STABILITY;
        _stability.samples.push(visibility);
        while (_stability.samples.length > cap) _stability.samples.shift();
        // Use the MIN over the window — punishes any frame that dropped
        // below the threshold during the stability period. This is what
        // prevents the score from jumping to 100 the instant a single
        // good frame slips through.
        let m = 100;
        for (const v of _stability.samples) if (v < m) m = v;
        return _stability.samples.length >= cap ? m : Math.min(m, visibility);
    }

    // ─── Cap curve ───────────────────────────────────────────────────
    function multiplierFor(stableVisibility) {
        const v = Math.max(0, Math.min(100, stableVisibility));
        const c = CONFIG.CAP_CURVE;
        // Walk the descending list to find the bracket; linear interp
        // between adjacent points so the cap is smooth, not stepped.
        for (let i = 0; i < c.length - 1; i++) {
            const a = c[i], b = c[i + 1];
            if (v <= a.vis && v >= b.vis) {
                const span = a.vis - b.vis;
                if (span <= 0) return a.mult;
                const t = (v - b.vis) / span; // 0 at b, 1 at a
                return b.mult + t * (a.mult - b.mult);
            }
        }
        return 0;
    }

    // ─── Public API ──────────────────────────────────────────────────
    function check(keypoints, poseName, video) {
        const required = requiredFor(poseName);
        const f = frameCheck(keypoints, video, required);
        const stableVisibility = pushStability(poseName, f.visibilityScore);
        const capMultiplier = multiplierFor(stableVisibility);

        let state;
        if (f.maxConfidence < CONFIG.OFF_FRAME_MAX_CONF || stableVisibility < CONFIG.OFF_FRAME_VISIBILITY) {
            state = 'OFF_FRAME';
        } else if (stableVisibility >= CONFIG.READY_VISIBILITY) {
            state = 'READY';
        } else {
            state = 'PARTIAL';
        }

        return {
            state,
            visibilityScore: f.visibilityScore,
            stableVisibility,
            missing: f.missing.slice(),
            required: required.slice(),
            maxConfidence: f.maxConfidence,
            capMultiplier,
            isMobile: isMobile(),
        };
    }

    function applyCap(formScore, readiness) {
        if (!readiness) return formScore;
        const capped = Math.min(formScore, readiness.stableVisibility * readiness.capMultiplier / (100 / 100));
        // Equivalent and simpler: take the smaller of formScore and
        // (stableVisibility * capMultiplier). Without dividing the user's
        // form score by anything, just clamp it.
        const ceiling = readiness.stableVisibility * readiness.capMultiplier;
        return Math.max(0, Math.min(formScore, ceiling));
    }

    // Pretty-print missing keypoint names for the on-screen banner.
    const NAME_LABELS = {
        'nose': 'face',
        'leftShoulder': 'left shoulder',  'rightShoulder': 'right shoulder',
        'leftElbow': 'left elbow',        'rightElbow': 'right elbow',
        'leftWrist': 'left wrist',        'rightWrist': 'right wrist',
        'leftHip': 'left hip',            'rightHip': 'right hip',
        'leftKnee': 'left knee',          'rightKnee': 'right knee',
        'leftAnkle': 'left ankle',        'rightAnkle': 'right ankle',
        'leftEye': 'left eye',            'rightEye': 'right eye',
    };
    function labelFor(name) { return NAME_LABELS[name] || name; }

    function reset() {
        _stability.poseName = null;
        _stability.samples = [];
    }

    root.PoseReadiness = {
        check,
        applyCap,
        requiredFor,
        labelFor,
        reset,
        isMobile,
        config: CONFIG,
    };
})(typeof window !== 'undefined' ? window : this);
