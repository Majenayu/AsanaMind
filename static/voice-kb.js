/*
 * Sunday · AsanaMind — Offline Voice Knowledge + Memory
 *
 * Pure-offline intelligence for the voice assistant. No server, no AI key.
 * Exposes:
 *   window.VoiceKB.POSE_CARDS — rich per-pose data (benefits, cautions,
 *                                mistakes, anatomy, progressions, cues)
 *   window.VoiceKB.answer(prompt, ctx) — best offline answer to a question,
 *                                         consulting the KB and local history
 *   window.VoiceKB.fuzzyPoseMatch(name) — Levenshtein-tolerant pose lookup
 *   window.VoiceKB.fuzzyCommandMatch(word, candidates) — generic fuzzy word
 *                                                         matcher for commands
 *   window.VoiceHistory.logSession({pose, peakScore, durationS, timestamp})
 *   window.VoiceHistory.recent(n)   — last n sessions
 *   window.VoiceHistory.summary()   — rolling stats (7 vs prior 7 days)
 *   window.VoiceHistory.weakest()   — pose with lowest rolling alignment
 */
(function () {
    'use strict';

    // ─────────────────────────────────────────────────────────────
    // POSE_CARDS — rich knowledge, one card per pose.
    // Keyed by lowercased English name (matches ASANA_LIBRARY.name.toLowerCase()).
    // ─────────────────────────────────────────────────────────────
    const POSE_CARDS = {
        'tadasana': {
            sanskrit: 'Tadasana',
            english: 'Mountain Pose',
            level: 'Beginner',
            meaning: 'Tada means mountain. Asana means seat.',
            benefit: 'Builds postural awareness, grounding, and mental clarity. Every standing asana starts here.',
            focus: 'Feet, ankles, core, spinal length.',
            mistake: 'Locking the knees or dumping into the low back. Stand active, not rigid.',
            caution: 'Avoid with low blood pressure or dizziness. Keep eyes open if balance is new.',
            progression: 'Once comfortable, try with eyes closed for thirty seconds to train proprioception.',
            cue: 'Feet hip-width, weight even, crown lifting to the ceiling.',
        },
        'urdhva hastasana': {
            sanskrit: 'Urdhva Hastasana',
            english: 'Upward Salute',
            level: 'Beginner',
            meaning: 'Urdhva means upward. Hasta means hand.',
            benefit: 'Opens the chest and side body. Resets posture and breathing.',
            focus: 'Shoulders, chest, lateral spine.',
            mistake: 'Shrugging the shoulders up to the ears.',
            caution: 'Drop arms slightly if shoulders strain; skip with shoulder impingement.',
            progression: 'Add a gentle backbend on the inhale.',
            cue: 'Sweep both arms overhead, palms face in, roll the shoulders down.',
        },
        'anjali mudra': {
            sanskrit: 'Anjali Mudra',
            english: 'Prayer at Heart',
            level: 'Beginner',
            meaning: 'Anjali means offering. Mudra means seal.',
            benefit: 'A centering gesture. Quiets the mind and opens the chest.',
            focus: 'Sternum, thumbs-to-heart contact, breath.',
            mistake: 'Hunching the shoulders or pressing too hard.',
            caution: 'Keep the spine tall; do not collapse the chest.',
            progression: 'Raise the mudra overhead for Anjali Urdhva.',
            cue: 'Palms together at the heart, thumbs touch the sternum.',
        },
        'vrikshasana': {
            sanskrit: 'Vrikshasana',
            english: 'Tree Pose',
            level: 'Beginner',
            meaning: 'Vriksha means tree.',
            benefit: 'Trains balance, focus, and ankle strength. Opens the inner thighs.',
            focus: 'Standing foot, standing hip, core, drishti (gaze).',
            mistake: 'Pressing the raised foot against the knee joint. Only on calf or thigh, never the knee.',
            caution: 'Use a wall for support if balance is new. Avoid with vertigo.',
            progression: 'Close the eyes once you can hold steady for a minute.',
            cue: 'Root the standing foot. Raised sole on the inner calf or thigh. Hands at heart.',
        },
        'uttanasana': {
            sanskrit: 'Uttanasana',
            english: 'Standing Forward Fold',
            level: 'Beginner',
            meaning: 'Ut means intense. Tan means to stretch.',
            benefit: 'Lengthens hamstrings and spine. Calms the nervous system.',
            focus: 'Hamstrings, lower back, neck release.',
            mistake: 'Rounding the low back by forcing the fold.',
            caution: 'Bend the knees generously if hamstrings are tight. Avoid with disc issues.',
            progression: 'Bind hands behind heels for a deeper fold.',
            cue: 'Hinge from the hips, soften the knees, let the head hang.',
        },
        'sukhasana': {
            sanskrit: 'Sukhasana',
            english: 'Easy Seated Pose',
            level: 'Beginner',
            meaning: 'Sukha means ease, comfort.',
            benefit: 'Foundation for breath work and meditation. Opens hips and lengthens spine.',
            focus: 'Pelvis, lumbar spine, relaxed shoulders.',
            mistake: 'Letting the pelvis tilt backward so the low back rounds.',
            caution: 'Sit on a cushion or block if the knees lift above the hips.',
            progression: 'Stay for five to ten minutes of breath work.',
            cue: 'Cross-legged, spine tall, hands on knees.',
        },
        'dandasana': {
            sanskrit: 'Dandasana',
            english: 'Staff Pose',
            level: 'Beginner',
            meaning: 'Danda means staff, stick.',
            benefit: 'The seated Tadasana. Teaches active legs and an upright spine.',
            focus: 'Quads, core, upright spine.',
            mistake: 'Letting the pelvis tip back so the torso collapses.',
            caution: 'Sit on a folded blanket if the pelvis tips backward.',
            progression: 'Stack for five breaths before moving into forward fold.',
            cue: 'Legs extended, flex the feet, press the palms down beside the hips.',
        },
        'baddha konasana': {
            sanskrit: 'Baddha Konasana',
            english: 'Bound Angle Pose',
            level: 'Beginner',
            meaning: 'Baddha means bound. Kona means angle.',
            benefit: 'Opens the inner thighs and hips. Stimulates abdominal organs.',
            focus: 'Adductors, hip capsules, upright spine.',
            mistake: 'Forcing the knees down. Let them release over time.',
            caution: 'Place blocks under the knees if they are high. Avoid with recent knee injury.',
            progression: 'Fold forward over the heels once the hips open.',
            cue: 'Soles together, knees wide, hands on feet or shins.',
        },
        'paschimottanasana': {
            sanskrit: 'Paschimottanasana',
            english: 'Seated Forward Fold',
            level: 'Beginner',
            meaning: 'Paschima means west, the back body.',
            benefit: 'Stretches the entire back body from heels to crown. Soothes the mind.',
            focus: 'Hamstrings, calves, spinal extension.',
            mistake: 'Rounding the low back to touch the toes.',
            caution: 'Bend knees if the low back rounds sharply. Avoid with disc injury.',
            progression: 'Hold for two to three minutes, letting the body soften.',
            cue: 'Fold from the hips, extend through the crown, reach for the feet.',
        },
        'balasana': {
            sanskrit: 'Balasana',
            english: 'Child\u2019s Pose',
            level: 'Beginner',
            meaning: 'Bala means child.',
            benefit: 'A resting pose between stronger asanas. Releases the back and quiets the mind.',
            focus: 'Lower back, hips, breath.',
            mistake: 'None really. If comfortable it\u2019s doing its job.',
            caution: 'Place a blanket between calves and thighs if knees are sensitive.',
            progression: 'Extend the arms forward for a shoulder stretch.',
            cue: 'Knees wide, hips to heels, forehead down, arms forward or at the sides.',
        },
        'adho mukha svanasana': {
            sanskrit: 'Adho Mukha Svanasana',
            english: 'Downward-Facing Dog',
            level: 'Intermediate',
            meaning: 'Adho means down. Mukha face. Svana dog.',
            benefit: 'Full-body tonic. Stretches the back line, strengthens arms, energises.',
            focus: 'Shoulders, hamstrings, calves, hands.',
            mistake: 'Collapsing the shoulders or locking the elbows.',
            caution: 'Avoid with carpal tunnel or uncontrolled high blood pressure.',
            progression: 'Pedal the heels and lift one leg at a time for three-legged dog.',
            cue: 'Hips high, arms straight, heels reaching down. Press through the palms.',
        },
        'virabhadrasana i': {
            sanskrit: 'Virabhadrasana I',
            english: 'Warrior I',
            level: 'Intermediate',
            meaning: 'Virabhadra was a fierce warrior.',
            benefit: 'Strengthens legs and core. Opens chest and hip flexors.',
            focus: 'Front quad, back hip flexor, shoulders, square hips.',
            mistake: 'Front knee drifting past the ankle. Back hip opening too far.',
            caution: 'Keep the front knee tracking over the ankle. Avoid with knee pain.',
            progression: 'Deepen the lunge, arms overhead, gaze up.',
            cue: 'Front knee bent ninety degrees, back leg straight, arms overhead.',
        },
        'virabhadrasana ii': {
            sanskrit: 'Virabhadrasana II',
            english: 'Warrior II',
            level: 'Intermediate',
            meaning: 'The warrior stance, eyes forward.',
            benefit: 'Builds stamina and focus. Opens hips, strengthens legs.',
            focus: 'Front quad, outer back leg, shoulders parallel to floor.',
            mistake: 'Front knee collapsing inward.',
            caution: 'Never let the front knee drift past the toes.',
            progression: 'Bend deeper so the front thigh is parallel to the floor.',
            cue: 'Front knee over ankle, arms parallel to the floor, gaze over the front hand.',
        },
        'utthita trikonasana': {
            sanskrit: 'Utthita Trikonasana',
            english: 'Extended Triangle',
            level: 'Intermediate',
            meaning: 'Utthita means extended. Trikona means triangle.',
            benefit: 'Stretches the side body, hamstrings, hips. Tones legs and core.',
            focus: 'Front hamstring, side waist, top shoulder.',
            mistake: 'Collapsing the chest toward the floor.',
            caution: 'Avoid with neck injury. Use a block under the lower hand.',
            progression: 'Gaze up toward the top hand.',
            cue: 'Front leg straight, torso reaches long, bottom hand to shin or block.',
        },
        'utkatasana': {
            sanskrit: 'Utkatasana',
            english: 'Chair Pose',
            level: 'Intermediate',
            meaning: 'Utkata means powerful, fierce.',
            benefit: 'Builds heat and strengthens the entire lower body. Engages the core.',
            focus: 'Quads, glutes, core, shoulders.',
            mistake: 'Knees sliding past the toes.',
            caution: 'Ease up if knees or low back feel pinched.',
            progression: 'Bring the knees together and sit lower.',
            cue: 'Knees bent as if sitting in a chair, arms overhead, weight in the heels.',
        },
        'utthita parsvakonasana': {
            sanskrit: 'Utthita Parsvakonasana',
            english: 'Extended Side Angle',
            level: 'Intermediate',
            meaning: 'Parsva means side. Kona angle.',
            benefit: 'Strengthens legs and opens the side body from heel to fingertips.',
            focus: 'Front quad, side waist, top arm reach.',
            mistake: 'Collapsing forward over the front thigh.',
            caution: 'Use a block under the lower hand if the torso collapses.',
            progression: 'Bind — thread the bottom arm under the thigh, top arm behind the back.',
            cue: 'Front knee bent, top arm reaches over the ear, bottom hand to floor or block.',
        },
        'setu bandhasana': {
            sanskrit: 'Setu Bandhasana',
            english: 'Bridge Pose',
            level: 'Intermediate',
            meaning: 'Setu means bridge. Bandha means lock.',
            benefit: 'Opens the chest and hip flexors. Strengthens the back body.',
            focus: 'Glutes, chest, upper back.',
            mistake: 'Letting the knees splay wide.',
            caution: 'Avoid with neck injury. Keep knees parallel.',
            progression: 'Clasp hands under the back and roll the shoulders beneath.',
            cue: 'On your back, feet hip-width near the sit bones, lift the hips.',
        },
        'virabhadrasana iii': {
            sanskrit: 'Virabhadrasana III',
            english: 'Warrior III',
            level: 'Advanced',
            meaning: 'The warrior in flight.',
            benefit: 'Challenges balance and strengthens the whole posterior chain.',
            focus: 'Standing glute, hamstrings, core, balance.',
            mistake: 'Opening the back hip to the ceiling.',
            caution: 'Practice near a wall if balance is new. Avoid with sciatica flare-ups.',
            progression: 'Extend the arms forward in a T, then behind like a diver.',
            cue: 'Torso and back leg parallel to the floor, arms forward, hips square.',
        },
        'ardha chandrasana': {
            sanskrit: 'Ardha Chandrasana',
            english: 'Half Moon',
            level: 'Advanced',
            meaning: 'Ardha means half. Chandra moon.',
            benefit: 'Builds balance, strengthens legs, opens the side body and chest.',
            focus: 'Standing glute, top hip opening, top arm reach.',
            mistake: 'Leaning forward instead of stacking the hips.',
            caution: 'Use a block under the bottom hand for support.',
            progression: 'Look up toward the top hand.',
            cue: 'One hand on a block, one foot down, top leg and arm reach long.',
        },
        'natarajasana': {
            sanskrit: 'Natarajasana',
            english: 'Dancer',
            level: 'Advanced',
            meaning: 'Nataraja is the cosmic dancer, Shiva.',
            benefit: 'Elegant balance that opens the chest, shoulders, and front body.',
            focus: 'Standing leg, back quad, chest opening, shoulder flexibility.',
            mistake: 'Collapsing forward instead of lifting the chest.',
            caution: 'Warm up the hamstrings and quads. Use a strap if you cannot reach the foot.',
            progression: 'Catch the inside of the back foot with both hands for a deep backbend.',
            cue: 'Stand on one leg, catch the back foot, arc the chest forward.',
        },
    };

    // Lookup alias → canonical pose card key.
    const ALIASES = {
        'mountain': 'tadasana', 'mountain pose': 'tadasana',
        'tree': 'vrikshasana', 'tree pose': 'vrikshasana',
        'prayer': 'anjali mudra', 'namaste': 'anjali mudra',
        'down dog': 'adho mukha svanasana', 'downward dog': 'adho mukha svanasana',
        'downward facing dog': 'adho mukha svanasana', 'downward-facing dog': 'adho mukha svanasana',
        'warrior one': 'virabhadrasana i', 'warrior 1': 'virabhadrasana i',
        'warrior two': 'virabhadrasana ii', 'warrior 2': 'virabhadrasana ii',
        'warrior three': 'virabhadrasana iii', 'warrior 3': 'virabhadrasana iii',
        'triangle': 'utthita trikonasana', 'extended triangle': 'utthita trikonasana',
        'chair': 'utkatasana', 'chair pose': 'utkatasana',
        'side angle': 'utthita parsvakonasana', 'extended side angle': 'utthita parsvakonasana',
        'bridge': 'setu bandhasana', 'bridge pose': 'setu bandhasana',
        'half moon': 'ardha chandrasana', 'dancer': 'natarajasana', 'dancer pose': 'natarajasana',
        'child': 'balasana', 'child pose': 'balasana', 'childs pose': 'balasana',
        "child's pose": 'balasana',
        'easy': 'sukhasana', 'easy seat': 'sukhasana', 'easy pose': 'sukhasana',
        'staff': 'dandasana', 'staff pose': 'dandasana',
        'bound angle': 'baddha konasana', 'butterfly': 'baddha konasana',
        'forward fold': 'paschimottanasana', 'seated forward fold': 'paschimottanasana',
        'standing forward fold': 'uttanasana', 'rag doll': 'uttanasana',
        'upward salute': 'urdhva hastasana', 'reach up': 'urdhva hastasana',
    };

    // ─────────────────────────────────────────────────────────────
    // Levenshtein distance — iterative, two-row DP.
    // Used for fuzzy speech matching ("tar dusana" → "tadasana").
    // ─────────────────────────────────────────────────────────────
    function levenshtein(a, b) {
        if (a === b) return 0;
        if (!a.length) return b.length;
        if (!b.length) return a.length;
        const prev = new Array(b.length + 1);
        const curr = new Array(b.length + 1);
        for (let j = 0; j <= b.length; j++) prev[j] = j;
        for (let i = 1; i <= a.length; i++) {
            curr[0] = i;
            for (let j = 1; j <= b.length; j++) {
                const cost = a[i - 1] === b[j - 1] ? 0 : 1;
                curr[j] = Math.min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
            }
            for (let j = 0; j <= b.length; j++) prev[j] = curr[j];
        }
        return prev[b.length];
    }

    /**
     * Fuzzy match a transcript against the pose library. Returns the best
     * pose card key (e.g. 'tadasana') or null. Tolerates up to ~25% edit
     * distance on a per-word basis so Chrome's mistranscription of Sanskrit
     * names still resolves.
     */
    function fuzzyPoseMatch(transcript) {
        const t = (transcript || '').toLowerCase().trim();
        if (!t) return null;

        // 1) Exact alias hit
        for (const alias of Object.keys(ALIASES)) {
            if (t.includes(alias)) return ALIASES[alias];
        }
        // 2) Exact canonical hit
        for (const key of Object.keys(POSE_CARDS)) {
            if (t.includes(key)) return key;
            const english = POSE_CARDS[key].english.toLowerCase();
            if (t.includes(english)) return key;
        }
        // 3) Fuzzy — word-by-word Levenshtein against every pose key and alias.
        const words = t.split(/\s+/);
        let best = { score: Infinity, key: null };
        const candidates = Object.keys(POSE_CARDS).concat(Object.keys(ALIASES));
        for (const cand of candidates) {
            const candWords = cand.split(/\s+/);
            for (const w of words) {
                if (w.length < 4) continue; // too-short words cause false positives
                for (const cw of candWords) {
                    if (cw.length < 4) continue;
                    const d = levenshtein(w, cw);
                    const threshold = Math.max(1, Math.floor(cw.length * 0.3));
                    if (d <= threshold && d < best.score) {
                        best = { score: d, key: POSE_CARDS[cand] ? cand : ALIASES[cand] };
                    }
                }
            }
        }
        return best.key;
    }

    /**
     * Generic fuzzy word matcher. Given a spoken word and a candidate list,
     * return the candidate within edit-distance threshold, or null.
     * Used to recover mis-heard commands like "diagnosis" → "diagnostics".
     */
    function fuzzyCommandMatch(word, candidates) {
        word = (word || '').toLowerCase();
        if (!word) return null;
        let best = { score: Infinity, cand: null };
        for (const c of candidates) {
            const cand = c.toLowerCase();
            const d = levenshtein(word, cand);
            const threshold = Math.max(1, Math.floor(cand.length * 0.3));
            if (d <= threshold && d < best.score) best = { score: d, cand };
        }
        return best.cand;
    }

    // ─────────────────────────────────────────────────────────────
    // Offline answer engine — consults POSE_CARDS, screen context,
    // and local session history to answer natural-language questions.
    // ─────────────────────────────────────────────────────────────
    function answer(prompt, ctx) {
        const q = (prompt || '').toLowerCase().trim();
        ctx = ctx || {};
        if (!q) return null;

        // Pose-specific: "tell me about tree pose" / "what are the benefits of warrior two"
        const fuzzy = fuzzyPoseMatch(q);
        if (fuzzy && POSE_CARDS[fuzzy]) {
            const card = POSE_CARDS[fuzzy];
            // Benefit-focused
            if (/\b(benefit|good for|help with|why (do|should) i)\b/.test(q)) {
                return `${card.sanskrit}, ${card.english}. ${card.benefit}`;
            }
            // Mistake-focused
            if (/\b(mistake|wrong|avoid|don't|dont|watch out)\b/.test(q)) {
                return `In ${card.sanskrit}: ${card.mistake} ${card.caution}`;
            }
            // Caution / safety
            if (/\b(safe|caution|injury|hurt|pain|contraindication)\b/.test(q)) {
                return `${card.sanskrit} — a note on safety: ${card.caution}`;
            }
            // Progression
            if (/\b(progress|deeper|next level|advance)\b/.test(q)) {
                return `${card.sanskrit} progression: ${card.progression}`;
            }
            // Meaning / etymology
            if (/\b(meaning|translate|sanskrit|name)\b/.test(q)) {
                return `${card.sanskrit} — ${card.meaning} ${card.english}, a ${card.level} pose.`;
            }
            // Default rich summary
            return `${card.sanskrit}, ${card.english}. ${card.benefit} Cue: ${card.cue}`;
        }

        // History questions — "how was my last session?", "what am I improving?"
        if (/\blast (session|practice|time)\b/.test(q)) {
            const last = VoiceHistory.recent(1)[0];
            if (!last) return 'No sessions logged yet. Start a pose and I\u2019ll remember it.';
            return `Your last session: ${last.poseSanskrit || last.pose}, peak alignment ${Math.round(last.peakScore)} percent, held ${Math.round(last.durationS)} seconds.`;
        }
        if (/\b(improving|getting better|progress this week|last week)\b/.test(q)) {
            const s = VoiceHistory.summary();
            if (!s.thisWeek.count) return 'No practice this week yet. One session and I can compare.';
            if (!s.lastWeek.count) return `This week: ${s.thisWeek.count} sessions at ${Math.round(s.thisWeek.avg)} percent. Keep going and I\u2019ll have a comparison.`;
            const diff = Math.round(s.thisWeek.avg - s.lastWeek.avg);
            const trend = diff > 3 ? `up ${diff} points` : diff < -3 ? `down ${Math.abs(diff)} points` : 'steady';
            return `This week: ${s.thisWeek.count} sessions at ${Math.round(s.thisWeek.avg)} percent, ${trend} vs last week.`;
        }
        if (/\b(weakest|need (to )?work|focus on|hardest)\b/.test(q)) {
            const weak = VoiceHistory.weakest();
            if (!weak) return 'Not enough history yet. Practise a few poses and ask again.';
            return `Your lowest rolling alignment is ${weak.poseSanskrit || weak.pose} at ${Math.round(weak.avg)} percent. Next session, start there.`;
        }

        return null; // no offline match — let caller fall through
    }

    // ─────────────────────────────────────────────────────────────
    // VoiceHistory — local, localStorage-backed session log.
    // ─────────────────────────────────────────────────────────────
    const HISTORY_KEY = 'sunday_voice_history';
    const MAX_HISTORY = 60;

    function _read() {
        try {
            const raw = localStorage.getItem(HISTORY_KEY);
            return raw ? (JSON.parse(raw) || []) : [];
        } catch (_) { return []; }
    }
    function _write(arr) {
        try { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(-MAX_HISTORY))); } catch (_) {}
    }

    const VoiceHistory = {
        /**
         * Log a completed session. Shape:
         * { pose: 'Tadasana', poseSanskrit: 'Mountain Pose',
         *   peakScore: 87, durationS: 42, ts: 17040000000 }
         */
        logSession(entry) {
            if (!entry || !entry.pose || entry.peakScore == null) return;
            const record = {
                pose: entry.pose,
                poseSanskrit: entry.poseSanskrit || null,
                peakScore: Number(entry.peakScore) || 0,
                durationS: Number(entry.durationS) || 0,
                ts: entry.ts || Date.now(),
            };
            const arr = _read();
            arr.push(record);
            _write(arr);
        },
        recent(n) {
            const arr = _read();
            return arr.slice(-Math.max(1, n || 5)).reverse();
        },
        /** Rolling summary: this week vs previous week. */
        summary() {
            const arr = _read();
            const now = Date.now();
            const weekMs = 7 * 24 * 3600 * 1000;
            const thisWeek = arr.filter(r => (now - r.ts) <= weekMs);
            const lastWeek = arr.filter(r => (now - r.ts) > weekMs && (now - r.ts) <= 2 * weekMs);
            const avg = a => a.length ? a.reduce((s, r) => s + r.peakScore, 0) / a.length : 0;
            return {
                thisWeek: { count: thisWeek.length, avg: avg(thisWeek) },
                lastWeek: { count: lastWeek.length, avg: avg(lastWeek) },
            };
        },
        /** Pose with the lowest rolling average over the last 14 days. */
        weakest() {
            const arr = _read();
            if (!arr.length) return null;
            const cutoff = Date.now() - 14 * 24 * 3600 * 1000;
            const buckets = {};
            for (const r of arr) {
                if (r.ts < cutoff) continue;
                (buckets[r.pose] = buckets[r.pose] || []).push(r);
            }
            let worst = null;
            for (const [pose, rs] of Object.entries(buckets)) {
                if (rs.length < 2) continue;
                const avg = rs.reduce((s, r) => s + r.peakScore, 0) / rs.length;
                const ps = rs[0].poseSanskrit;
                if (!worst || avg < worst.avg) worst = { pose, poseSanskrit: ps, avg };
            }
            return worst;
        },
        clear() { try { localStorage.removeItem(HISTORY_KEY); } catch(_) {} },
    };

    window.VoiceKB = { POSE_CARDS, ALIASES, fuzzyPoseMatch, fuzzyCommandMatch, answer };
    window.VoiceHistory = VoiceHistory;
})();
