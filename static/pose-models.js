/*
 * AsanMinds — multi-model pose dispatcher.
 *
 * Picks the best-suited keypoint detector for each yoga pose and
 * normalises every model's output into a single MoveNet-COCO-17
 * keypoint shape so the existing rule engine doesn't care which
 * model produced the data.
 *
 *   MoveNet SinglePose Thunder  — default for upright + standing poses
 *   MediaPipe BlazePose Lite    — seated, forward-folded, hip-opener poses
 *   MediaPipe BlazePose Heavy   — supine, prone, asymmetric advanced poses
 *
 * Public API:
 *   PoseModelDispatcher.getDetector(modelKey)  -> Promise<detector>
 *   PoseModelDispatcher.normaliseKeypoints(keypoints, modelKey) -> COCO-17
 *   PoseModelDispatcher.bonusKeypoints(keypoints, modelKey) -> map of extras
 *
 * Lazy loading: BlazePose vendor JS is fetched the first time a
 * BlazePose-tagged pose is opened. Subsequent loads come from the
 * service-worker cache. MoveNet is already vendored in
 * /static/vendor and /static/models/movenet.
 */
(function () {
    'use strict';

    if (typeof poseDetection === 'undefined') {
        console.warn('[PoseModelDispatcher] @tensorflow-models/pose-detection not loaded yet');
    }

    // ─────────────────────────────────────────────────────────
    // BlazePose vendor files — try the locally-vendored copy first
    // (so the campus / offline kiosk works without internet), fall
    // back to the JSDelivr CDN if the local copy isn't present yet.
    //
    // To populate /static/vendor/mediapipe-pose/, run:
    //     python scripts/fetch_offline_assets.py
    //
    // The MediaPipe pose runtime auto-loads its wasm + tflite siblings
    // from the same `solutionPath` directory, so vendoring all of them
    // together is required. If even one file is missing we transparently
    // fall back to the CDN by detecting the script load error.
    // ─────────────────────────────────────────────────────────
    const BLAZEPOSE_LOCAL_BASE = '/static/vendor/mediapipe-pose';
    const BLAZEPOSE_CDN_BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/pose@0.5.1675469404';

    let _depsLoaded = false;
    let _depsBase = BLAZEPOSE_LOCAL_BASE; // resolved during ensureBlazePoseDeps()
    async function ensureBlazePoseDeps() {
        if (_depsLoaded) return;
        // Try local first; on script error, fall back to the CDN. We probe
        // the local path with a HEAD request so we don't spuriously inject a
        // <script> that 404s and produces a noisy console error.
        async function probe(base) {
            try {
                const r = await fetch(base + '/pose.js', { method: 'HEAD' });
                return r.ok;
            } catch (_) { return false; }
        }
        const useLocal = await probe(BLAZEPOSE_LOCAL_BASE);
        _depsBase = useLocal ? BLAZEPOSE_LOCAL_BASE : BLAZEPOSE_CDN_BASE;
        const src = _depsBase + '/pose.js';
        await new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${src}"]`)) return resolve();
            const s = document.createElement('script');
            s.src = src;
            // Local same-origin doesn't need crossOrigin; CDN does.
            if (!useLocal) s.crossOrigin = 'anonymous';
            s.async = true;
            s.onload = resolve;
            s.onerror = () => {
                // Last-ditch CDN fallback — the local copy partially loaded
                // but threw. Replace with the CDN version.
                _depsBase = BLAZEPOSE_CDN_BASE;
                const fallback = document.createElement('script');
                fallback.src = BLAZEPOSE_CDN_BASE + '/pose.js';
                fallback.crossOrigin = 'anonymous';
                fallback.async = true;
                fallback.onload = resolve;
                fallback.onerror = reject;
                document.head.appendChild(fallback);
            };
            document.head.appendChild(s);
        });
        _depsLoaded = true;
    }

    // ─────────────────────────────────────────────────────────
    // Detector cache — one detector per model key
    // ─────────────────────────────────────────────────────────
    const detectorCache = {};

    async function getDetector(modelKey) {
        modelKey = modelKey || 'movenet-thunder';
        if (detectorCache[modelKey]) return detectorCache[modelKey];

        if (modelKey === 'movenet-thunder' || modelKey === 'movenet-lightning') {
            const isLightning = modelKey === 'movenet-lightning'
                || sessionStorage.getItem('sunday_movenet_fallback') === 'lightning';
            const cfg = {
                modelType: isLightning
                    ? poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING
                    : poseDetection.movenet.modelType.SINGLEPOSE_THUNDER,
                enableSmoothing: true,
                minPoseScore: 0.3,
                modelUrl: isLightning ? undefined : '/static/models/movenet/model.json',
            };
            detectorCache[modelKey] = await poseDetection.createDetector(
                poseDetection.SupportedModels.MoveNet, cfg
            );
            return detectorCache[modelKey];
        }

        if (modelKey === 'blazepose-lite' || modelKey === 'blazepose-heavy') {
            await ensureBlazePoseDeps();
            const cfg = {
                runtime: 'mediapipe',
                modelType: modelKey === 'blazepose-heavy' ? 'heavy' : 'lite',
                enableSmoothing: true,
                // Same base as the pose.js script — local if vendored, CDN otherwise.
                solutionPath: _depsBase,
            };
            detectorCache[modelKey] = await poseDetection.createDetector(
                poseDetection.SupportedModels.BlazePose, cfg
            );
            return detectorCache[modelKey];
        }

        throw new Error(`Unknown model key: ${modelKey}`);
    }

    // ─────────────────────────────────────────────────────────
    // Keypoint normalisation
    //
    // MoveNet returns 17 COCO keypoints already named (nose,
    // left_eye, ..., right_ankle). BlazePose returns 33 indexed
    // landmarks named (nose, left_eye_inner, ...). We map a curated
    // 17 BlazePose landmarks back to the COCO names so every rule
    // in the existing engine works unchanged.
    //
    // BlazePose index reference (from MediaPipe docs):
    //    0  nose                11  left_shoulder    23  left_hip
    //    2  left_eye             12  right_shoulder   24  right_hip
    //    5  right_eye            13  left_elbow       25  left_knee
    //    7  left_ear             14  right_elbow      26  right_knee
    //    8  right_ear            15  left_wrist       27  left_ankle
    //                            16  right_wrist      28  right_ankle
    // ─────────────────────────────────────────────────────────
    const BLAZEPOSE_TO_COCO = {
        nose:           0,
        left_eye:       2,
        right_eye:      5,
        left_ear:       7,
        right_ear:      8,
        left_shoulder:  11,
        right_shoulder: 12,
        left_elbow:     13,
        right_elbow:    14,
        left_wrist:     15,
        right_wrist:    16,
        left_hip:       23,
        right_hip:      24,
        left_knee:      25,
        right_knee:     26,
        left_ankle:     27,
        right_ankle:    28,
    };

    // BlazePose-only landmarks the rule engine can opt into when it
    // knows it's running under BlazePose. Used for bonus rules in the
    // seated/lying poses.
    const BLAZEPOSE_BONUS = {
        mouth_left:     9,
        mouth_right:    10,
        left_pinky:     17,
        right_pinky:    18,
        left_index:     19,
        right_index:    20,
        left_thumb:     21,
        right_thumb:    22,
        left_heel:      29,
        right_heel:     30,
        left_foot_index:31,
        right_foot_index:32,
    };

    function normaliseKeypoints(raw, modelKey) {
        if (!raw || !raw.length) return raw;
        if (modelKey === 'blazepose-lite' || modelKey === 'blazepose-heavy') {
            // Build COCO-named array from BlazePose indices.
            const out = [];
            for (const [cocoName, bpIdx] of Object.entries(BLAZEPOSE_TO_COCO)) {
                const kp = raw[bpIdx];
                if (kp) {
                    out.push({
                        name: cocoName,
                        x: kp.x,
                        y: kp.y,
                        score: kp.score != null ? kp.score : (kp.visibility != null ? kp.visibility : 0),
                    });
                } else {
                    out.push({ name: cocoName, x: 0, y: 0, score: 0 });
                }
            }
            return out;
        }
        // MoveNet — already COCO-shaped.
        return raw;
    }

    function bonusKeypoints(raw, modelKey) {
        if (modelKey !== 'blazepose-lite' && modelKey !== 'blazepose-heavy') return {};
        const out = {};
        for (const [name, idx] of Object.entries(BLAZEPOSE_BONUS)) {
            const kp = raw && raw[idx];
            if (kp) {
                out[name] = {
                    x: kp.x, y: kp.y,
                    score: kp.score != null ? kp.score : (kp.visibility || 0),
                };
            }
        }
        return out;
    }

    // ─────────────────────────────────────────────────────────
    // Convenience: ask the dispatcher which model a pose wants
    // ─────────────────────────────────────────────────────────
    function modelFor(pose) {
        const tag = pose && pose.preferredModel;
        if (tag === 'blazepose-lite' || tag === 'blazepose-heavy'
            || tag === 'movenet-lightning' || tag === 'movenet-thunder') {
            return tag;
        }
        return 'movenet-thunder';
    }

    function dispose() {
        for (const k of Object.keys(detectorCache)) {
            try { detectorCache[k].dispose && detectorCache[k].dispose(); } catch (_) {}
            delete detectorCache[k];
        }
    }

    window.PoseModelDispatcher = {
        getDetector,
        normaliseKeypoints,
        bonusKeypoints,
        modelFor,
        dispose,
        BLAZEPOSE_TO_COCO,
        BLAZEPOSE_BONUS,
    };
})();
