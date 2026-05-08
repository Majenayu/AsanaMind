/*
 * Sunday · AsanaMind — Pose Library + Rule Engine
 *
 * 20 curated asanas, each with:
 *   - declarative pose rules evaluated against MoveNet (17-keypoint, 2D)
 *   - reference keypoints that render a consistent SVG silhouette
 *   - camera view hint (front/side) so users set up correctly
 *
 * Public globals:
 *   window.ASANA_LIBRARY   — array of 20 pose records
 *   window.asanaData        — alias (legacy)
 *   window.PoseEngine       — { evaluate(keypoints, poseName) }
 *   window.PoseImage        — { svg(pose), dataUri(pose) }
 */
(function () {
    'use strict';

    const MIN_CONFIDENCE = 0.3;

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
    // RULE EVALUATORS
    // Each returns { pass, measured?, skipped? }
    // ─────────────────────────────────────────────────────────────
    const evaluators = {
        angle(kp, rule) {
            const [a, b, c] = rule.joints;
            const A = kp[a], B = kp[b], C = kp[c];
            if (!A || !B || !C) return { pass: true, skipped: true };
            const deg = angleDeg(A, B, C);
            const [min, max] = rule.range;
            return { pass: deg >= min && deg <= max, measured: deg };
        },
        alignY(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            return { pass: Math.abs(A.y - B.y) / torso <= (rule.tolFrac || 0.15) };
        },
        alignX(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            return { pass: Math.abs(A.x - B.x) / torso <= (rule.tolFrac || 0.2) };
        },
        distance(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const ratio = dist(A, B) / torso;
            const min = rule.minFrac == null ? 0 : rule.minFrac;
            const max = rule.maxFrac == null ? Infinity : rule.maxFrac;
            return { pass: ratio >= min && ratio <= max, measured: ratio };
        },
        higher(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            return { pass: A.y + (rule.bufferFrac || 0) * torso < B.y };
        },
        lower(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            return { pass: A.y > B.y + (rule.bufferFrac || 0) * torso };
        },
        symmetric(kp, rule) {
            const [aL, bL, cL, aR, bR, cR] = rule.joints;
            const L = (kp[aL] && kp[bL] && kp[cL]) ? angleDeg(kp[aL], kp[bL], kp[cL]) : null;
            const R = (kp[aR] && kp[bR] && kp[cR]) ? angleDeg(kp[aR], kp[bR], kp[cR]) : null;
            if (L == null || R == null) return { pass: true, skipped: true };
            return { pass: Math.abs(L - R) <= (rule.tolDeg || 15) };
        },
        horizontalSpan(kp, rule) {
            const A = kp[rule.joints[0]], B = kp[rule.joints[1]];
            if (!A || !B) return { pass: true, skipped: true };
            const torso = torsoLength(kp);
            const dx = Math.abs(A.x - B.x) / torso, dy = Math.abs(A.y - B.y) / torso;
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

            const kp = {};
            for (const k of keypoints) {
                if (k && k.score >= MIN_CONFIDENCE) kp[k.name] = { x: k.x, y: k.y };
            }

            const required = pose.required || ['left_hip', 'right_hip', 'left_shoulder', 'right_shoulder', 'nose'];
            const missing = required.filter(r => !kp[r]);
            if (missing.length > 2) {
                return {
                    corrections: [{ message: 'Step back so your full body is in frame', affected: required, color: 'red', priority: 1 }],
                    score: 0,
                };
            }

            if (!pose.rules || !pose.rules.length) {
                return { corrections: [{ message: 'Hold the pose calmly and breathe.', color: 'green', priority: 0, affected: [] }], score: 80 };
            }

            const corrections = [];
            let totalWeight = 0, passWeight = 0;

            for (const rule of pose.rules) {
                const evalFn = evaluators[rule.type];
                if (!evalFn) continue;
                const weight = rule.priority === 1 ? 3 : rule.priority === 2 ? 2 : 1;
                totalWeight += weight;
                const result = evalFn(kp, rule);
                if (result.skipped || result.pass) {
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
            corrections.sort((a, b) => (a.priority || 5) - (b.priority || 5));
            const top = corrections.slice(0, 3);

            if (top.length === 0) {
                top.push({ message: `Beautiful ${pose.name}. Hold and breathe.`, affected: [], color: 'green', priority: 0 });
            } else if (score >= 80) {
                top.unshift({ message: 'Close. Small refinements below.', affected: [], color: 'blue', priority: 0 });
            }

            return { corrections: top, score };
        },
    };

    // ─────────────────────────────────────────────────────────────
    // POSE IMAGE RENDERER
    // Renders an SVG silhouette from a pose's reference keypoints.
    // Coordinates are in a 0..1 normalised space (origin top-left).
    // ─────────────────────────────────────────────────────────────
    // 17 MoveNet keypoints in order. Bones connect adjacent joints.
    const BONES = [
        ['left_shoulder', 'right_shoulder'],
        ['left_shoulder', 'left_elbow'], ['left_elbow', 'left_wrist'],
        ['right_shoulder', 'right_elbow'], ['right_elbow', 'right_wrist'],
        ['left_shoulder', 'left_hip'], ['right_shoulder', 'right_hip'],
        ['left_hip', 'right_hip'],
        ['left_hip', 'left_knee'], ['left_knee', 'left_ankle'],
        ['right_hip', 'right_knee'], ['right_knee', 'right_ankle'],
    ];

    function poseSvg(pose, opts) {
        opts = opts || {};
        const w = opts.width || 400;
        const h = opts.height || 500;
        const bg = opts.bg || '#F3EEE5';
        const body = opts.body || '#1E2E1F';
        const joint = opts.joint || '#D4A04A';
        const kp = pose.referenceKeypoints || {};
        const toX = v => (v * w * 0.7 + w * 0.15).toFixed(1);
        const toY = v => (v * h * 0.78 + h * 0.11).toFixed(1);

        // Head circle derived from nose keypoint if available.
        const nose = kp.nose;
        let headSvg = '';
        if (nose) {
            const cx = toX(nose.x), cy = toY(nose.y);
            headSvg = `<circle cx="${cx}" cy="${cy}" r="22" fill="${body}"/>`;
        }

        // Bones
        let boneSvg = '';
        for (const [a, b] of BONES) {
            if (kp[a] && kp[b]) {
                boneSvg += `<line x1="${toX(kp[a].x)}" y1="${toY(kp[a].y)}" x2="${toX(kp[b].x)}" y2="${toY(kp[b].y)}" stroke="${body}" stroke-width="14" stroke-linecap="round"/>`;
            }
        }
        // Neck bone (nose → mid-shoulder)
        if (nose && kp.left_shoulder && kp.right_shoulder) {
            const mx = (kp.left_shoulder.x + kp.right_shoulder.x) / 2;
            const my = (kp.left_shoulder.y + kp.right_shoulder.y) / 2;
            boneSvg += `<line x1="${toX(nose.x)}" y1="${toY(nose.y)}" x2="${toX(mx)}" y2="${toY(my)}" stroke="${body}" stroke-width="14" stroke-linecap="round"/>`;
        }

        // Joints
        let jointSvg = '';
        for (const name of Object.keys(kp)) {
            if (name === 'nose') continue;
            jointSvg += `<circle cx="${toX(kp[name].x)}" cy="${toY(kp[name].y)}" r="5.5" fill="${joint}"/>`;
        }

        // View indicator
        const viewBadge = pose.view ? `
            <g opacity="0.85">
                <rect x="20" y="${h - 50}" rx="14" ry="14" width="88" height="28" fill="${body}"/>
                <text x="64" y="${h - 31}" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="11" font-weight="600" fill="#D4A04A" letter-spacing="1.8">${pose.view.toUpperCase()} VIEW</text>
            </g>` : '';

        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="100%" height="100%" role="img" aria-label="${pose.name} reference pose">
            <rect width="${w}" height="${h}" fill="${bg}"/>
            <circle cx="${w*0.82}" cy="${h*0.18}" r="46" fill="#D4A04A" opacity="0.22"/>
            <circle cx="${w*0.14}" cy="${h*0.86}" r="60" fill="#B8573E" opacity="0.14"/>
            ${boneSvg}
            ${headSvg}
            ${jointSvg}
            ${viewBadge}
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
            referenceKeypoints: KP_TADASANA,
            rules: [
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 0.25, maxFrac: 0.75, message: 'Feet hip-width apart', priority: 2 },
                { type: 'alignY', joints: ['left_ankle', 'right_ankle'], tolFrac: 0.08, message: 'Weight even on both feet', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [162, 198], message: 'Engage left quadriceps, straighten knee', priority: 1 },
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [162, 198], message: 'Engage right quadriceps, straighten knee', priority: 1 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.1, message: 'Level your hips', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Relax shoulders, keep them level', priority: 2 },
                { type: 'distance', joints: ['left_shoulder', 'right_shoulder'], minFrac: 0.7, maxFrac: 1.4, message: 'Broaden the collarbones', priority: 3 },
                { type: 'alignX', joints: ['nose', 'left_hip'], tolFrac: 0.18, message: 'Crown of head over the body', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, lengthen the spine', priority: 2 },
                { type: 'lower', joints: ['left_wrist', 'left_hip'], bufferFrac: 0.1, message: 'Let the arms rest by your sides', priority: 3 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.1, message: 'Let the arms rest by your sides', priority: 3 },
                { type: 'symmetric', joints: ['left_hip', 'left_knee', 'left_ankle', 'right_hip', 'right_knee', 'right_ankle'], tolDeg: 10, message: 'Stand evenly on both legs', priority: 2 },
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
                'Press the bases of the palms and thumbs against the sternum.',
                'Keep elbows wide and collarbones broad.',
                'Soften the gaze; take three slow breaths.',
            ],
            referenceKeypoints: KP_ANJALI,
            rules: [
                { type: 'distance', joints: ['left_wrist', 'right_wrist'], minFrac: 0, maxFrac: 0.18, message: 'Press palms firmly together at the heart', priority: 1 },
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
                'Place right sole on left inner calf or thigh (not the knee).',
                'Press the foot into the leg and the leg into the foot.',
                'Hands at heart or reach them up.',
            ],
            referenceKeypoints: KP_VRIKSHASANA,
            rules: [
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [162, 198], message: 'Standing leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['right_ankle', 'left_knee'], bufferFrac: 0.1, message: 'Lift the raised foot higher onto the inner leg', priority: 1 },
                { type: 'higher', joints: ['right_knee', 'right_hip'], bufferFrac: -0.05, message: 'Open the bent knee out to the side', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'right_shoulder'], tolFrac: 0.1, message: 'Shoulders level, do not lean', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.12, message: 'Level your hips', priority: 2 },
                { type: 'alignX', joints: ['nose', 'left_ankle'], tolFrac: 0.2, message: 'Stack crown over the standing foot', priority: 2 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, lengthen the spine', priority: 2 },
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
            referenceKeypoints: KP_VIR1,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [85, 115], message: 'Bend the front knee to 90 degrees', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [150, 200], message: 'Straighten and ground the back leg', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.3, message: 'Lift the arms overhead, alongside the ears', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: 0.3, message: 'Reach both arms up evenly', priority: 2 },
                { type: 'alignX', joints: ['right_knee', 'right_ankle'], tolFrac: 0.15, message: 'Front knee tracks over the front ankle', priority: 1 },
                { type: 'higher', joints: ['left_shoulder', 'left_hip'], bufferFrac: 0.5, message: 'Lift the chest, open the heart', priority: 2 },
                { type: 'symmetric', joints: ['left_shoulder', 'left_elbow', 'left_wrist', 'right_shoulder', 'right_elbow', 'right_wrist'], tolDeg: 18, message: 'Arms reach up evenly', priority: 3 },
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
            referenceKeypoints: KP_VIR2,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [85, 115], message: 'Front knee bends to 90, tracks over the ankle', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
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
            referenceKeypoints: KP_TRIKON,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [155, 200], message: 'Front leg strong and straight', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.2, message: 'Stack the top arm directly above the bottom', priority: 2 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm toward the ceiling', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.05, message: 'Lower the bottom hand to shin or block', priority: 2 },
                { type: 'distance', joints: ['left_ankle', 'right_ankle'], minFrac: 1.6, maxFrac: 3.5, message: 'Widen the stance for the triangle shape', priority: 2 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 200], message: 'Extend the top arm fully', priority: 3 },
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
            referenceKeypoints: KP_PARSVA,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [85, 115], message: 'Front knee bent to 90 degrees', priority: 1 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [155, 200], message: 'Back leg strong and straight', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Reach the top arm up and over the ear', priority: 2 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.3, message: 'Lengthen the side body from hip to fingertips', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0, message: 'Lower the front hand to forearm, block, or floor', priority: 2 },
                { type: 'alignX', joints: ['right_knee', 'right_ankle'], tolFrac: 0.15, message: 'Front knee tracks over the ankle', priority: 1 },
                { type: 'angle', joints: ['left_shoulder', 'left_elbow', 'left_wrist'], range: [150, 200], message: 'Top arm straight over the ear', priority: 3 },
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
            referenceKeypoints: KP_VIR3,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Fully straighten the standing leg', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.2, message: 'Lift the back leg parallel to the floor', priority: 1 },
                { type: 'alignY', joints: ['left_shoulder', 'left_hip'], tolFrac: 0.2, message: 'Bring the torso parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: -0.05, message: 'Reach the arms forward at shoulder height', priority: 2 },
                { type: 'higher', joints: ['right_wrist', 'right_shoulder'], bufferFrac: -0.05, message: 'Reach the arms forward at shoulder height', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Extend the back leg fully, flex the foot', priority: 2 },
                { type: 'alignY', joints: ['left_hip', 'right_hip'], tolFrac: 0.15, message: 'Keep the hips level, do not open the back hip', priority: 2 },
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
            referenceKeypoints: KP_HALFMOON,
            rules: [
                { type: 'angle', joints: ['right_hip', 'right_knee', 'right_ankle'], range: [160, 200], message: 'Straighten the standing leg fully', priority: 1 },
                { type: 'alignY', joints: ['left_ankle', 'left_hip'], tolFrac: 0.3, message: 'Float the top leg parallel to the floor', priority: 1 },
                { type: 'higher', joints: ['left_wrist', 'left_shoulder'], bufferFrac: 0.2, message: 'Stack the top arm straight up', priority: 2 },
                { type: 'alignX', joints: ['left_wrist', 'right_wrist'], tolFrac: 0.3, message: 'Line the top arm above the bottom arm', priority: 2 },
                { type: 'angle', joints: ['left_hip', 'left_knee', 'left_ankle'], range: [160, 200], message: 'Extend the lifted leg, flex the foot', priority: 2 },
                { type: 'lower', joints: ['right_wrist', 'right_hip'], bufferFrac: 0.1, message: 'Ground the bottom hand for support', priority: 2 },
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
