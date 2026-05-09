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

    // ─────────────────────────────────────────────────────────────
    // RAG FALLBACK — tf-idf retrieval over a semantic corpus.
    //
    // Called AFTER the direct-hit keyword answers in VoiceKB.answer but
    // BEFORE the server AI proxy. Closes the gap for natural-language
    // queries that don't contain exact KB keywords, like:
    //   "I have shoulder pain"        → Downward Dog caution + neck release
    //   "something calming before bed" → Child's Pose, Paschimottanasana
    //   "I sit at a desk all day"      → Chest openers + hip flexor openers
    //
    // Deliberately small: the corpus is ~60 chunks, tf-idf vectors stay
    // in memory, every query is one dot-product loop. No embeddings model,
    // no WASM download, no server. ~4 KB added to voice-kb.js.
    // ─────────────────────────────────────────────────────────────

    // Hand-authored symptom / condition / goal mini-KB. This is the layer
    // that makes "my back hurts" actually work.
    const SYMPTOM_KB = [
        { tag: 'back pain', poses: ['Setu Bandhasana', 'Balasana', 'Paschimottanasana'],
          text: 'For back pain, try Bridge Pose to strengthen the posterior chain, Child\u2019s Pose to decompress the spine, and a slow Seated Forward Fold. Move with the breath, never force.' },
        { tag: 'lower back stiffness', poses: ['Balasana', 'Setu Bandhasana'],
          text: 'Low-back stiffness eases with Child\u2019s Pose and Bridge Pose. Hold each for five long breaths. Keep knees wide and belly soft.' },
        { tag: 'tight hips', poses: ['Baddha Konasana', 'Sukhasana', 'Utthita Parsvakonasana'],
          text: 'For tight hips, work with Bound Angle Pose and Extended Side Angle. Sit on a cushion if the knees lift. Let the pelvis open gradually, never yank.' },
        { tag: 'tight hamstrings', poses: ['Paschimottanasana', 'Uttanasana', 'Adho Mukha Svanasana'],
          text: 'Tight hamstrings respond to Seated Forward Fold, Standing Forward Fold, and Down Dog. Bend the knees generously \u2014 length over depth.' },
        { tag: 'shoulder tension', poses: ['Urdhva Hastasana', 'Balasana', 'Setu Bandhasana'],
          text: 'Shoulder tension releases with Upward Salute to open the chest, Child\u2019s Pose with arms long, and Bridge clasping hands beneath the back.' },
        { tag: 'neck pain', poses: ['Balasana', 'Sukhasana'],
          text: 'For neck relief, start with Child\u2019s Pose and gentle seated neck rolls in Sukhasana. Skip deep inversions while the neck is sensitive.' },
        { tag: 'tight chest desk posture', poses: ['Urdhva Hastasana', 'Setu Bandhasana', 'Natarajasana'],
          text: 'After hours at a desk, open the chest with Upward Salute, Bridge, and eventually Dancer. They counter the rounded-shoulder posture.' },
        { tag: 'anxiety stress calm', poses: ['Balasana', 'Paschimottanasana', 'Sukhasana'],
          text: 'For anxiety, Child\u2019s Pose and Seated Forward Fold turn the practice inward. Pair with long exhales and box breath for quick calm.' },
        { tag: 'trouble sleeping insomnia', poses: ['Balasana', 'Paschimottanasana', 'Setu Bandhasana'],
          text: 'Before sleep: Child\u2019s Pose, Seated Forward Fold, and supported Bridge. Slow the exhale until it is twice the inhale.' },
        { tag: 'tired fatigue low energy', poses: ['Adho Mukha Svanasana', 'Urdhva Hastasana', 'Virabhadrasana II'],
          text: 'Feeling tired or low energy or fatigued, wake the body with Down Dog, Upward Salute, and two rounds of Warrior II. Movement first, then breath.' },
        { tag: 'morning routine wake up', poses: ['Tadasana', 'Urdhva Hastasana', 'Uttanasana', 'Adho Mukha Svanasana'],
          text: 'A simple morning sequence: Mountain, Upward Salute, Forward Fold, Down Dog. Five breaths each. Repeat twice.' },
        { tag: 'evening wind down', poses: ['Sukhasana', 'Paschimottanasana', 'Balasana'],
          text: 'Evening practice: Easy Seat for breath, Seated Forward Fold, Child\u2019s Pose. Dim the lights, slow everything down.' },
        { tag: 'build strength', poses: ['Virabhadrasana I', 'Virabhadrasana II', 'Utkatasana', 'Adho Mukha Svanasana'],
          text: 'To build strength: Warrior I, Warrior II, Chair Pose, and Down Dog. Hold each for thirty seconds. Breath stays even.' },
        { tag: 'balance', poses: ['Vrikshasana', 'Natarajasana', 'Virabhadrasana III', 'Ardha Chandrasana'],
          text: 'Balance work: Tree, Dancer, Warrior III, Half Moon. Fix the gaze on one still point. Near a wall if new.' },
        { tag: 'flexibility', poses: ['Paschimottanasana', 'Baddha Konasana', 'Uttanasana', 'Utthita Trikonasana'],
          text: 'Flexibility builds slowly with Seated Forward Fold, Bound Angle, Standing Forward Fold, and Triangle. Consistency beats depth.' },
        { tag: 'core abs strength', poses: ['Utkatasana', 'Virabhadrasana III', 'Adho Mukha Svanasana'],
          text: 'Core work in poses: Chair Pose holds the trunk, Warrior III demands the deep line, Down Dog stabilises through the shoulders.' },
        { tag: 'knees knee pain', poses: ['Sukhasana', 'Dandasana', 'Setu Bandhasana'],
          text: 'If knees are sensitive, lean on Easy Seat, Staff Pose, and Bridge. Avoid deep lunges and Chair Pose until the knees settle.' },
        { tag: 'pregnancy prenatal', poses: ['Baddha Konasana', 'Sukhasana', 'Balasana'],
          text: 'Always consult your doctor in pregnancy. Gentle Bound Angle, Easy Seat, and a wide-kneed Child\u2019s Pose are commonly recommended.' },
        { tag: 'high blood pressure hypertension', poses: ['Balasana', 'Sukhasana', 'Paschimottanasana'],
          text: 'With high blood pressure, avoid strong inversions and long holds in Down Dog. Child\u2019s Pose, seated forward folds, and long slow exhales are safer.' },
        { tag: 'headache migraine', poses: ['Balasana', 'Paschimottanasana'],
          text: 'Headaches often ease with Child\u2019s Pose and a supported Seated Forward Fold. Keep the head below the heart briefly, and breathe slowly.' },
        { tag: 'digestion bloating', poses: ['Baddha Konasana', 'Setu Bandhasana', 'Paschimottanasana'],
          text: 'For digestion: Bound Angle and gentle forward folds massage the belly. Bridge also lengthens the front body.' },
        { tag: 'focus concentration', poses: ['Vrikshasana', 'Tadasana', 'Virabhadrasana III'],
          text: 'To sharpen focus: Tree, Mountain, and Warrior III. A fixed gaze point trains the mind the way it trains the body.' },
        { tag: 'breathing breath pranayama', poses: ['Sukhasana', 'Tadasana'],
          text: 'For breath work: sit in Easy Seat or stand in Mountain. Ujjayi breath during practice, box-breath four-four-four-four for calm.' },
    ];

    // Build the retrieval corpus from POSE_CARDS, SYMPTOM_KB, and app KB.
    // Each chunk: { id, text, doc, tags[] } — text is what gets tokenised.
    function _buildCorpus() {
        const corpus = [];
        // Pose cards — one chunk per pose, plus sub-chunks per field so
        // "mistake in warrior two" can retrieve the mistake line directly.
        for (const key of Object.keys(POSE_CARDS)) {
            const c = POSE_CARDS[key];
            const base = `${c.sanskrit} ${c.english} ${c.level}`;
            corpus.push({ id: `${key}:overview`, doc: c.english, text: `${base} ${c.benefit} ${c.cue}`, reply: `${c.sanskrit}, ${c.english}. ${c.benefit} Cue: ${c.cue}` });
            corpus.push({ id: `${key}:benefit`, doc: c.english, text: `benefit ${base} ${c.benefit} ${c.focus}`, reply: `${c.sanskrit} — ${c.benefit}` });
            corpus.push({ id: `${key}:mistake`, doc: c.english, text: `mistake wrong error ${base} ${c.mistake}`, reply: `Common mistake in ${c.sanskrit}: ${c.mistake}` });
            corpus.push({ id: `${key}:caution`, doc: c.english, text: `caution safety injury pain ${base} ${c.caution}`, reply: `${c.sanskrit} caution: ${c.caution}` });
            corpus.push({ id: `${key}:meaning`, doc: c.english, text: `meaning name sanskrit ${base} ${c.meaning}`, reply: `${c.sanskrit} — ${c.meaning} ${c.english}, ${c.level}.` });
            corpus.push({ id: `${key}:progression`, doc: c.english, text: `progression deeper advance ${base} ${c.progression}`, reply: `${c.sanskrit} progression: ${c.progression}` });
        }
        // Symptom / goal entries
        for (let i = 0; i < SYMPTOM_KB.length; i++) {
            const s = SYMPTOM_KB[i];
            corpus.push({ id: `symptom:${i}`, doc: s.tag, text: `${s.tag} ${s.poses.join(' ')} ${s.text}`, reply: s.text });
        }
        return corpus;
    }

    // ─────────────────────────────────────────────────────────────
    // tf-idf indexer. Standard BoW + cosine. ~50 lines, zero deps.
    // ─────────────────────────────────────────────────────────────
    const STOP = new Set([
        'the', 'a', 'an', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has',
        'had', 'do', 'does', 'did', 'how', 'what', 'why', 'when', 'where',
        'which', 'who', 'can', 'should', 'would', 'could', 'will', 'me',
        'my', 'i', 'you', 'your', 'it', 'this', 'that', 'about', 'with',
        'tell', 'show', 'explain', 'please',
    ]);

    function _tokenize(s) {
        return (s || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/)
            .filter(w => w && w.length >= 3 && !STOP.has(w));
    }

    let _index = null; // { corpus, docVectors, idf, terms }

    function _buildIndex() {
        const corpus = _buildCorpus();
        const df = {};
        const docTokens = corpus.map(c => {
            const toks = _tokenize(c.text);
            const seen = new Set();
            for (const t of toks) {
                if (!seen.has(t)) { df[t] = (df[t] || 0) + 1; seen.add(t); }
            }
            return toks;
        });
        const N = corpus.length;
        const idf = {};
        for (const t of Object.keys(df)) idf[t] = Math.log((N + 1) / (df[t] + 1)) + 1;

        const docVectors = docTokens.map(toks => {
            const tf = {};
            for (const t of toks) tf[t] = (tf[t] || 0) + 1;
            const vec = {};
            let norm = 0;
            for (const t of Object.keys(tf)) {
                const w = (tf[t] / toks.length) * (idf[t] || 0);
                vec[t] = w;
                norm += w * w;
            }
            norm = Math.sqrt(norm) || 1;
            for (const t of Object.keys(vec)) vec[t] /= norm;
            return vec;
        });

        _index = { corpus, docVectors, idf };
    }

    function _queryVector(query) {
        const toks = _tokenize(query);
        if (!toks.length) return null;
        const tf = {};
        for (const t of toks) tf[t] = (tf[t] || 0) + 1;
        const vec = {};
        let norm = 0;
        for (const t of Object.keys(tf)) {
            const idf = _index.idf[t];
            if (!idf) continue; // out-of-vocab term, skip
            const w = (tf[t] / toks.length) * idf;
            vec[t] = w;
            norm += w * w;
        }
        norm = Math.sqrt(norm);
        if (norm === 0) return null;
        for (const t of Object.keys(vec)) vec[t] /= norm;
        return vec;
    }

    function _cosine(q, d) {
        let sum = 0;
        for (const t of Object.keys(q)) if (d[t]) sum += q[t] * d[t];
        return sum;
    }

    /**
     * Run a tf-idf search. Returns an array of { chunk, score } sorted
     * descending by similarity, top `k` results (default 3). Returns []
     * if no tokens overlap the vocabulary or no result crosses `minScore`.
     */
    function rag(query, opts) {
        opts = opts || {};
        const k = opts.k || 3;
        const minScore = opts.minScore != null ? opts.minScore : 0.15;
        if (!_index) _buildIndex();
        const q = _queryVector(query);
        if (!q) return [];
        const scored = _index.docVectors.map((d, i) => ({ chunk: _index.corpus[i], score: _cosine(q, d) }));
        scored.sort((a, b) => b.score - a.score);
        return scored.filter(r => r.score >= minScore).slice(0, k);
    }

    /**
     * High-level convenience — returns a spoken-ready reply for a query,
     * or null if no chunk scores above threshold. Called by the main
     * app as the layer between VoiceKB.answer (direct hits) and the
     * server AI proxy (network-dependent).
     */
    function ragAnswer(query) {
        const hits = rag(query, { k: 2, minScore: 0.12 });
        if (!hits.length) return null;
        // If the top-1 is clearly strongest, return it alone.
        if (hits.length === 1 || hits[0].score > hits[1].score * 1.4) {
            return hits[0].chunk.reply;
        }
        // Otherwise stitch the two most relevant replies together when
        // they're from different docs (gives "back pain" a longer answer).
        if (hits[0].chunk.doc !== hits[1].chunk.doc) {
            return hits[0].chunk.reply + ' ' + hits[1].chunk.reply;
        }
        return hits[0].chunk.reply;
    }

    window.VoiceKB.rag = rag;
    window.VoiceKB.ragAnswer = ragAnswer;
    window.VoiceKB.SYMPTOM_KB = SYMPTOM_KB;

    // ─────────────────────────────────────────────────────────────
    // EXPANDED SYMPTOM KB (item 28) — additional conditions
    // ─────────────────────────────────────────────────────────────
    SYMPTOM_KB.push(
        { tag: 'tennis elbow wrist pain', poses: ['Anjali Mudra', 'Sukhasana'],
          text: 'For wrist or elbow strain, avoid weight-bearing on the hands. Rest in Anjali Mudra and Easy Seat. Consult a physio if it persists.' },
        { tag: 'plantar fasciitis foot pain', poses: ['Dandasana', 'Sukhasana'],
          text: 'With foot pain, avoid standing poses that load the arch. Staff Pose and Easy Seat keep you practising without aggravating the foot.' },
        { tag: 'sciatica nerve pain', poses: ['Balasana', 'Sukhasana'],
          text: 'Sciatica flares with deep forward folds and Warrior III. Stay with Child\u2019s Pose and gentle seated work until it settles.' },
        { tag: 'vertigo dizziness', poses: ['Sukhasana', 'Dandasana'],
          text: 'With vertigo, skip standing balance poses and inversions. Seated poses like Easy Seat and Staff Pose are safe.' },
        { tag: 'wrist pain carpal tunnel', poses: ['Sukhasana', 'Setu Bandhasana'],
          text: 'Avoid Down Dog and plank with wrist pain. Bridge and seated poses keep you moving without loading the wrists.' },
        { tag: 'hip replacement surgery', poses: ['Sukhasana', 'Dandasana', 'Setu Bandhasana'],
          text: 'After hip surgery, always follow your surgeon\u2019s guidance. Gentle seated work and supported Bridge are common starting points.' },
        { tag: 'rounded shoulders posture', poses: ['Urdhva Hastasana', 'Setu Bandhasana', 'Virabhadrasana I'],
          text: 'For rounded shoulders, open the chest with Upward Salute, Bridge, and Warrior I. Think of drawing the shoulder blades together.' },
        { tag: 'tight calves', poses: ['Adho Mukha Svanasana', 'Uttanasana'],
          text: 'Tight calves release in Down Dog (pedal the heels) and Standing Forward Fold with bent knees.' },
        { tag: 'weak core', poses: ['Utkatasana', 'Virabhadrasana III', 'Adho Mukha Svanasana'],
          text: 'Build core strength with Chair Pose holds, Warrior III, and Down Dog. Keep the low belly firm in every pose.' },
        { tag: 'post-run recovery', poses: ['Uttanasana', 'Adho Mukha Svanasana', 'Paschimottanasana', 'Baddha Konasana'],
          text: 'After running: Forward Fold for hamstrings, Down Dog for calves, Seated Forward Fold for the back, Bound Angle for hips.' }
    );

    // ─────────────────────────────────────────────────────────────
    // YOGA PHILOSOPHY KB (item 29)
    // ─────────────────────────────────────────────────────────────
    SYMPTOM_KB.push(
        { tag: 'eight limbs patanjali yoga philosophy', poses: [],
          text: 'Patanjali\u2019s eight limbs: yama (ethics), niyama (self-discipline), asana (posture), pranayama (breath), pratyahara (withdrawal), dharana (focus), dhyana (meditation), samadhi (absorption). Asana is just one of eight.' },
        { tag: 'yama niyama ethics', poses: [],
          text: 'The yamas are non-violence, truthfulness, non-stealing, moderation, and non-possessiveness. The niyamas are cleanliness, contentment, discipline, self-study, and surrender.' },
        { tag: 'chakra energy', poses: [],
          text: 'The seven chakras run from the base of the spine to the crown. Each relates to a quality: root (security), sacral (creativity), solar plexus (will), heart (love), throat (expression), third eye (intuition), crown (connection).' },
        { tag: 'pranayama breath control', poses: ['Sukhasana', 'Tadasana'],
          text: 'Pranayama means breath control. Ujjayi (ocean breath) for practice, Nadi Shodhana (alternate nostril) for calm, Kapalabhati (skull-shining) for energy. Always practise seated or standing.' },
        { tag: 'namaste meaning', poses: [],
          text: 'Namaste means \u201cthe light in me honours the light in you.\u201d It\u2019s a gesture of respect, not worship. Palms together at the heart, a slight bow.' },
        { tag: 'om aum meaning', poses: [],
          text: 'Om (AUM) represents the sound of the universe. A = creation, U = preservation, M = dissolution. Chanting it at the start and end of practice centres the mind.' }
    );

    // ─────────────────────────────────────────────────────────────
    // CONVERSATIONAL MEMORY (item 2) — last 5 turns in sessionStorage
    // so pronouns resolve: "tell me about tree" then "show me" knows.
    // ─────────────────────────────────────────────────────────────
    const MEMORY_KEY = 'sunday_conv_memory';
    const MAX_TURNS = 5;

    function _readMemory() {
        try { return JSON.parse(sessionStorage.getItem(MEMORY_KEY) || '[]'); } catch(_) { return []; }
    }
    function _writeMemory(arr) {
        try { sessionStorage.setItem(MEMORY_KEY, JSON.stringify(arr.slice(-MAX_TURNS))); } catch(_){}
    }

    const ConvMemory = {
        /** Record a turn: { role: 'user'|'assistant', text, poseMentioned? } */
        push(turn) {
            const arr = _readMemory();
            arr.push(turn);
            _writeMemory(arr);
        },
        /** Get the last mentioned pose from recent turns. */
        lastPose() {
            const arr = _readMemory();
            for (let i = arr.length - 1; i >= 0; i--) {
                if (arr[i].poseMentioned) return arr[i].poseMentioned;
            }
            return null;
        },
        /** Resolve pronouns: "show me" / "tell me more" / "its benefits" → last pose. */
        resolvePronouns(query) {
            const q = (query || '').toLowerCase();
            const pronouns = /\b(it|its|this|that|this one|the pose|show me|tell me more|more about it)\b/;
            if (!pronouns.test(q)) return null;
            return this.lastPose();
        },
        recent() { return _readMemory(); },
        clear() { try { sessionStorage.removeItem(MEMORY_KEY); } catch(_){} },
    };

    window.VoiceKB.ConvMemory = ConvMemory;

    // Rebuild the RAG index since we added new SYMPTOM_KB entries.
    _index = null;
})();
