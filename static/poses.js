/*
 * Sunday · AsanaMind — Pose Library + Rule Engine
 *
 * 20 curated asanas, each with declarative pose rules evaluated against
 * MoveNet (17-keypoint, 2D) keypoints. Works for PC webcams and phone
 * cameras when the full body is visible at ~6–8 feet, front or side view
 * as specified per pose.
 *
 * Public API:
 *   window.ASANA_LIBRARY  — array of pose records
 *   window.asanaData       — alias (for backwards compatibility)
 *   window.PoseEngine      — { evaluate(keypoints, poseName) }
 */
(function () {
    'use strict';

    const MIN_CONFIDENCE = 0.3;

    // ─────────────────────────────────────────────────────────────
    // GEOMETRY HELPERS
    // ─────────────────────────────────────────────────────────────
    const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const midpoint = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

    // Angle at vertex B, formed by A-B-C. Returns 0-180 degrees.
    function angleDeg(A, B, C) {
        if (!A || !B || !C) return 180;
        const AB = dist(A, B), BC = dist(B, C), AC = dist(A, C);
        if (AB === 0 || BC === 0) return 180;
        const cos = (AB * AB + BC * BC - AC * AC) / (2 * AB * BC);
        return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
    }

    // Torso length = average shoulder → average hip. Used to normalise tolerances
    // so the same rules work whether the user is close or far from the camera.
    function torsoLength(kp) {
        const ls = kp.left_shoulder, rs = kp.right_shoulder;
        const lh = kp.left_hip, rh = kp.right_hip;
        if (!ls || !rs || !lh || !rh) return 120; // sensible default in pixels
        const shoulder = midpoint(ls, rs), hip = midpoint(lh, rh);
        return Math.max(40, dist(shoulder, hip));
    }

    // ─────────────────────────────────────────────────────────────
    // RULE EVALUATORS
    // Each returns { pass: boolean, measured?: number, message?: string }
    // ─────────────────────────────────────────────────────────────
    const evaluators = {
        // Joint angle at a vertex. joints = [A, B, C] where B is the vertex.
        angle(kp, rule) {
            const [a, b, c] = rule.joints;
            const A = kp[a], B = kp[b], C = kp[c];
            if (!A || !B || !C) return { pass: true, skipped: true };
            const deg = angleDeg(A, B, C);
            const [min, max] = rule.range;
            return { pass: deg >= min && deg <= max, measured: deg };
        },

        // Two points should be level on Y (horizontal alignment).
        // tolFrac = fraction of torso length.
        alignY(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const diff = Math.abs(A.y - B.y) / torso;
            return { pass: diff <= (rule.tolFrac || 0.15), measured: diff };
        },

        // Two points should be on the same vertical (X aligned).
        alignX(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const diff = Math.abs(A.x - B.x) / torso;
            return { pass: diff <= (rule.tolFrac || 0.2), measured: diff };
        },

        // Normalised distance. Pass if ratio (dist/torso) is within [minFrac, maxFrac].
        distance(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const ratio = dist(A, B) / torso;
            const min = rule.minFrac == null ? 0 : rule.minFrac;
            const max = rule.maxFrac == null ? Infinity : rule.maxFrac;
            return { pass: ratio >= min && ratio <= max, measured: ratio };
        },

        // First joint should be above second in the frame (smaller Y).
        // bufferFrac lets you require A is clearly above B (A.y + buffer < B.y).
        higher(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const buffer = (rule.bufferFrac || 0) * torso;
            return { pass: A.y + buffer < B.y, measured: (B.y - A.y) / torso };
        },

        // First joint below second (larger Y).
        lower(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const buffer = (rule.bufferFrac || 0) * torso;
            return { pass: A.y > B.y + buffer, measured: (A.y - B.y) / torso };
        },

        // Two different angles should be approximately equal (symmetry).
        symmetric(kp, rule) {
            const [aL, bL, cL, aR, bR, cR] = rule.joints;
            const L = (kp[aL] && kp[bL] && kp[cL]) ? angleDeg(kp[aL], kp[bL], kp[cL]) : null;
            const R = (kp[aR] && kp[bR] && kp[cR]) ? angleDeg(kp[aR], kp[bR], kp[cR]) : null;
            if (L == null || R == null) return { pass: true, skipped: true };
            return { pass: Math.abs(L - R) <= (rule.tolDeg || 15) };
        },

        // Horizontal line check: two points roughly on same Y (like triangle's arms).
        horizontalSpan(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const dx = Math.abs(A.x - B.x) / torso;
            const dy = Math.abs(A.y - B.y) / torso;
            // Pass if mostly horizontal: dx large, dy small
            return { pass: dx > (rule.minDx || 0.6) && dy < (rule.maxDy || 0.3) };
        },
    };

    // ─────────────────────────────────────────────────────────────
    // ENGINE
    // ─────────────────────────────────────────────────────────────
    const PoseEngine = {
        evaluate(keypoints, poseName) {
            const pose = ASANA_LIBRARY.find(p => p.name === poseName);
            if (!pose) {
                return { corrections: [{ message: 'Pose not configured', color: 'yellow', priority: 3, affected: [] }], score: 0 };
            }

            // Normalise keypoints to { name → {x,y} }, skipping low-confidence.
            const kp = {};
            for (const k of keypoints) {
                if (k && k.score >= MIN_CONFIDENCE) kp[k.name] = { x: k.x, y: k.y };
            }

            // Global visibility check.
            const required = pose.required || ['left_hip', 'right_hip', 'left_shoulder', 'right_shoulder', 'nose'];
            const missing = required.filter(r => !kp[r]);
            if (missing.length > 2) {
                return {
                    corrections: [{
                        message: 'Step back so your full body is in frame',
                        affected: required,
                        color: 'red',
                        priority: 1,
                    }],
                    score: 0,
                };
            }

            if (!pose.rules || pose.rules.length === 0) {
                return { corrections: [{ message: 'Hold the pose calmly and breathe.', color: 'green', priority: 0, affected: [] }], score: 80 };
            }

            // Run every rule, collect corrections and score.
            const corrections = [];
            let totalWeight = 0;
            let passWeight = 0;

            for (const rule of pose.rules) {
                const evalFn = evaluators[rule.type];
                if (!evalFn) continue;
                const weight = rule.priority === 1 ? 3 : rule.priority === 2 ? 2 : 1;
                totalWeight += weight;
                const result = evalFn(kp, rule);
                if (result.skipped) {
                    // Skipped rules count as pass (missing limb, not visible).
                    passWeight += weight;
                } else if (result.pass) {
                    passWeight += weight;
                } else {
                    corrections.push({
                        message: rule.message,
                        affected: rule.affected || rule.joints || [],
                        color: rule.severity || (rule.priority === 1 ? 'red' : 'yellow'),
                        priority: rule.priority || 3,
                    });
                }
            }

            const score = totalWeight > 0 ? Math.round((passWeight / totalWeight) * 100) : 100;

            // Sort by priority, keep the top 3.
            corrections.sort((a, b) => (a.priority || 5) - (b.priority || 5));
            const topCorrections = corrections.slice(0, 3);

            if (topCorrections.length === 0) {
                topCorrections.push({
                    message: `Beautiful ${pose.name}. Hold and breathe.`,
                    affected: [],
                    color: 'green',
                    priority: 0,
                });
            } else if (score >= 80) {
                topCorrections.unshift({
                    message: 'Close. Small refinements below.',
                    affected: [],
                    color: 'blue',
                    priority: 0,
                });
            }

            return { corrections: topCorrections, score };
        },
    };

    // ─────────────────────────────────────────────────────────────
    // LIBRARY (20 POSES)
    // Each pose is front- or side-view; MoveNet works for both.
    // ─────────────────────────────────────────────────────────────
    const ASANA_LIBRARY = [
        // ─── BEGINNER (10) ─────────────────────────────────────
        {
            name: 'Tadasana',
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
            rules: [
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 0.2, maxFrac: 0.7, message: 'Feet hip-width apart, parallel', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Engage quadriceps, straighten left knee', priority: 1 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Engage quadriceps, straighten right knee', priority: 1 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.1, message: 'Level your hips', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Relax shoulders; keep them level', priority: 2 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.25, message: 'Crown of head over the body, neutral neck', priority: 2 },
            ],
        },
        {
            name: 'Urdhva Hastasana',
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
            rules: [
                { type: 'higher', joints: ['left_wrist', 'nose'], bufferFrac: 0.4, message: 'Reach the left hand higher above your head', priority: 1 },
                { type: 'higher', joints: ['right_wrist', 'nose'], bufferFrac: 0.4, message: 'Reach the right hand higher above your head', priority: 1 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 190], message: 'Straighten the left arm', priority: 2 },
                { type: 'angle', joints: ['right_shoulder', 'right_elbow', 'right_wrist'], range: [150, 190], message: 'Straighten the right arm', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Keep the left leg strong and straight', priority: 2 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Keep the right leg strong and straight', priority: 2 },
            ],
        },
        {
            name: 'Anjali Mudra',
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
                'Press the bases of the palms and the thumbs against the sternum.',
                'Keep elbows wide and collarbones broad.',
                'Soften the gaze; take three slow breaths.',
            ],
            rules: [
                { type: 'distance', joints: ['left_wrist', 'right_wrist'], minFrac: 0, maxFrac: 0.2, message: 'Press palms firmly together at the heart', priority: 1 },
                { type: 'alignY', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.1, message: 'Keep both wrists at the same height', priority: 2 },
                { type: 'distance', joints: ['left_elbow', 'right_elbow'], minFrac: 0.6, maxFrac: 1.4, message: 'Widen the elbows to open the chest', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Relax and level the shoulders', priority: 2 },
            ],
        },
        {
            name: 'Vrikshasana',
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
                'Place right sole on left inner calf or thigh, not the knee.',
                'Press the foot into the leg and the leg into the foot.',
                'Hands at heart or reach them up.',
            ],
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Standing leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['right_ankle', 'left_knee'], bufferFrac: 0.1, message: 'Lift the raised foot higher onto the inner leg', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Shoulders level — do not lean', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.15, message: 'Level your hips', priority: 2 },
            ],
        },
        {
            name: 'Uttanasana',
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
            rules: [
                { type: 'higher', joints: ['left_hip', 'left_shoulder'], bufferFrac: 0.2, message: 'Hinge deeper from the hips, not the back', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Keep a soft, long line through the leg', priority: 2 },
                { type: 'alignY', joints: ['nose', 'left_knee'], tolFrac: 0.4, message: 'Let the head soften down toward the shins', priority: 3 },
            ],
        },
        {
            name: 'Sukhasana',
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
            rules: [
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.3, message: 'Lift the spine tall — shoulders above hips', priority: 1 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.15, message: 'Sit evenly on both sit bones', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.15, message: 'Level the shoulders', priority: 2 },
            ],
        },
        {
            name: 'Dandasana',
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
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Straighten the legs, engage the thighs', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.3, message: 'Lengthen the spine up, shoulders above hips', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Keep shoulders level', priority: 2 },
            ],
        },
        {
            name: 'Baddha Konasana',
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
            rules: [
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 0, maxFrac: 0.3, message: 'Bring the heels closer together', priority: 2 },
                { type: 'distance', joints: ['left_knee', 'right_knee'], minFrac: 0.8, maxFrac: 2.5, message: 'Let the knees widen out to the sides', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.25, message: 'Lift the chest, lengthen the spine', priority: 2 },
                { type: 'symmetric', joints: ['left_hip', 'left_knee', 'left_ankle', 'right_hip', 'right_knee', 'right_ankle'], tolDeg: 20, message: 'Open the hips evenly on both sides', priority: 3 },
            ],
        },
        {
            name: 'Paschimottanasana',
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
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Keep the legs long; a small bend is fine', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'left_knee'], tolFrac: 0.5, message: 'Fold deeper over the legs, leading with the chest', priority: 1 },
                { type: 'lower', joints: ['left_wrist', 'left_knee'], bufferFrac: 0, message: 'Reach the hands toward the feet', priority: 2 },
            ],
        },
        {
            name: 'Balasana',
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
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [20, 90], message: 'Sink the hips back toward the heels', priority: 1 },
                { type: 'lower', joints: ['left_shoulder', 'left_knee'], bufferFrac: 0, message: 'Relax the torso over the thighs', priority: 1 },
                { type: 'lower', joints: ['nose', 'left_shoulder'], bufferFrac: 0.1, message: 'Rest the forehead down, release the neck', priority: 2 },
            ],
        },

        // ─── INTERMEDIATE (7) ─────────────────────────────────
        {
            name: 'Adho Mukha Svanasana',
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
            rules: [
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [160, 200], message: 'Straighten the arms, press through the palms', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Lengthen through the legs; a small bend is fine', priority: 2 },
                { type: 'higher', joints: ['left_hip', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the hips higher, pike the shape', priority: 1 },
                { type: 'higher', joints: ['left_hip', 'left_knee'], bufferFrac: 0.2, message: 'Send the hips up and back toward the ceiling', priority: 1 },
            ],
        },
        {
            name: 'Virabhadrasana I',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [80, 115], message: 'Bend the front knee to 90 degrees', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Straighten and ground the back leg', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the arms overhead, alongside the ears', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: 0.3, message: 'Reach the arms up evenly', priority: 2 },
            ],
        },
        {
            name: 'Virabhadrasana II',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [80, 115], message: 'Front knee bends to 90, tracks over the ankle', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'horizontalSpan', joints: ['left_wrist', 'right_wrist'], minDx: 0.9, maxDy: 0.2, message: 'Arms out wide, parallel to the floor', priority: 2 },
                { type: 'alignY', joints: ['left_wrist', 'left_shoulder'], tolFrac: 0.2, message: 'Lift the arms to shoulder height', priority: 2 },
            ],
        },
        {
            name: 'Utthita Trikonasana',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [155, 200], message: 'Front leg strong and straight', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.3, message: 'Stack the top arm directly above the bottom', priority: 2 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm toward the ceiling', priority: 2 },
            ],
        },
        {
            name: 'Utkatasana',
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
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [90, 140], message: 'Sit lower into the chair shape', priority: 1 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [90, 140], message: 'Sit lower into the chair shape', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the arms up alongside the ears', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: 0.3, message: 'Reach both hands up evenly', priority: 2 },
            ],
        },
        {
            name: 'Utthita Parsvakonasana',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [80, 115], message: 'Front knee bent to 90 degrees', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm up and over the ear', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.4, message: 'Lengthen the side body from hip to fingertips', priority: 2 },
            ],
        },
        {
            name: 'Setu Bandhasana',
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
            rules: [
                { type: 'higher', joints: ['left_hip', 'left_shoulder'], bufferFrac: 0.15, message: 'Lift the hips higher toward the ceiling', priority: 1 },
                { type: 'higher', joints: ['left_hip', 'left_knee'], bufferFrac: 0.05, message: 'Drive the hips up, not out', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [70, 120], message: 'Stack knees over ankles', priority: 2 },
            ],
        },

        // ─── ADVANCED (3) ──────────────────────────────────────
        {
            name: 'Virabhadrasana III',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Fully straighten the standing leg', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.25, message: 'Lift the back leg parallel to the floor', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.25, message: 'Bring the torso parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.1, message: 'Reach the arms forward at shoulder height', priority: 2 },
            ],
        },
        {
            name: 'Ardha Chandrasana',
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
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Straighten the standing leg fully', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.3, message: 'Float the top leg parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Stack the top arm straight up', priority: 2 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.35, message: 'Line the top arm above the bottom arm', priority: 2 },
            ],
        },
        {
            name: 'Natarajasana',
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
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Standing leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['right_ankle', 'right_hip'], bufferFrac: 0.1, message: 'Kick the back foot high behind you', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.15, message: 'Reach the front arm forward and up', priority: 2 },
            ],
        },
    ];

    // Expose globals.
    window.ASANA_LIBRARY = ASANA_LIBRARY;
    window.asanaData = ASANA_LIBRARY; // legacy alias
    window.PoseEngine = PoseEngine;
})();
