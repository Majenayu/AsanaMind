/*
 * Sunday · AsanaMind — Per-Pose Cue Library
 *
 * Every one of the 20 asanas has its own signature corrections, so a
 * generic "Level the hips" is too vague. This module maps generic rule
 * messages to pose-specific spoken lines that reference the actual
 * anatomy and action of THIS asana.
 *
 * Shape:
 *   POSE_CUES[poseName] = {
 *     opening: [...]   // 1–3 opening lines spoken once when the pose starts
 *     holding: [...]   // rotated lines spoken while the pose is held well
 *     cues: {          // generic-cue → pose-specific rewrites
 *       'knee over ankle': { long: '...', short: '...' },
 *       ...
 *     },
 *     exit: '...'      // spoken when the user stops the session
 *   }
 *
 * The main.html frame loop calls PoseCues.personalise(correction, poseName)
 * which returns a rewritten { message, shortMessage } tuned to the current
 * asana. If no rewrite exists it falls back to the generic cue unchanged.
 *
 * Keys in `cues` match the patterns produced by shortenCue() in poses.js,
 * plus a few full-phrase keys for rules that don't shorten cleanly.
 */
(function () {
    'use strict';

    // Generic matcher — keys tried in order against the correction.message.
    // Match = substring, case-insensitive. First hit wins.
    const GENERIC_MATCHERS = [
        { key: 'knee over ankle',    test: /knee.*(ankle|track|over)/i },
        { key: 'knee past toes',     test: /knee.*(past|over|past the toes)/i },
        { key: 'knee not past toes', test: /knee back|not past.*toes|past.*toes/i },
        { key: 'straighten leg',     test: /straighten.*(leg|standing)/i },
        { key: 'bend knee deeper',   test: /bend.*deeper|sit lower|knee (deeper|bent)/i },
        { key: 'level hips',         test: /hips? level|level the hips|open.*hip/i },
        { key: 'square hips',        test: /square.*hips|hips? square|turn.*hip/i },
        { key: 'lift chest',         test: /lift.*chest|chest up/i },
        { key: 'open chest',         test: /open.*chest/i },
        { key: 'lengthen spine',     test: /lengthen.*spine|tall spine|spine (long|tall)/i },
        { key: 'drop shoulders',     test: /relax.*shoulders?|drop.*shoulders?|shoulders? down/i },
        { key: 'extend arms',        test: /arms? (parallel|level|straight|overhead|forward|high)/i },
        { key: 'reach overhead',     test: /overhead|reach up/i },
        { key: 'engage core',        test: /engage.*core|core on/i },
        { key: 'root feet',          test: /press.*feet|root.*foot|ground the feet|weight even/i },
        { key: 'flex foot',          test: /flex.*foot/i },
        { key: 'soften gaze',        test: /gaze/i },
        { key: 'lift hips',          test: /lift.*hips|hips (up|higher)/i },
        { key: 'knees parallel',     test: /knees? (parallel|hip-width)/i },
        { key: 'heels down',         test: /heels? (down|reach)/i },
        { key: 'hand to block',      test: /block|lower hand/i },
        { key: 'breathe',            test: /breathe|breath/i },
    ];

    function _matchKey(message) {
        for (const m of GENERIC_MATCHERS) if (m.test.test(message)) return m.key;
        return null;
    }

    // ─────────────────────────────────────────────────────────────
    // Pose-specific cue library. Each pose maps generic keys to its
    // own language. Long form = full sentence; short = 2-5 words used
    // for priority-1 interrupts.
    // ─────────────────────────────────────────────────────────────
    const POSE_CUES = {
        // ─── BEGINNER ────────────────────────────────────────
        'Tadasana': {
            opening: ['Tadasana. Find your mountain.', 'Feet parallel, weight even.'],
            holding: ['Crown lifting. Shoulders soft.', 'Feel the ground through both feet.'],
            cues: {
                'root feet':      { long: 'Press all four corners of both feet into the ground',      short: 'Root the feet' },
                'lengthen spine': { long: 'Lift the crown of the head toward the ceiling',             short: 'Crown up' },
                'drop shoulders': { long: 'Let the shoulders melt down the back',                      short: 'Shoulders down' },
                'engage core':    { long: 'Draw the navel gently toward the spine',                    short: 'Navel in' },
                'soften gaze':    { long: 'Eyes soft, fixed on one point at eye level',                short: 'Soft gaze forward' },
            },
            exit: 'Mountain settles. Breathe.',
        },
        'Urdhva Hastasana': {
            opening: ['Upward Salute. Reach the sky.'],
            holding: ['Side body long. Breathe into the ribs.'],
            cues: {
                'reach overhead': { long: 'Stretch both arms high, palms facing or touching',          short: 'Arms high' },
                'extend arms':    { long: 'Reach the fingertips farther away',                         short: 'Reach long' },
                'drop shoulders': { long: 'Keep the shoulders rolling down away from the ears',        short: 'Shoulders away from ears' },
                'open chest':     { long: 'Let the front ribs lift, chest opens up',                   short: 'Open the heart' },
                'root feet':      { long: 'Ground the feet as the arms reach up',                      short: 'Feet grounded' },
            },
            exit: 'Lower the arms with control.',
        },
        'Anjali Mudra': {
            opening: ['Anjali Mudra. Palms together at the heart.'],
            holding: ['Thumbs touch the sternum. Steady breath.'],
            cues: {
                'lift chest':     { long: 'Lift the sternum into the base of the thumbs',              short: 'Chest to thumbs' },
                'drop shoulders': { long: 'Shoulders soft and wide, not hunched forward',              short: 'Shoulders wide' },
                'lengthen spine': { long: 'Crown rises as the heart presses forward',                  short: 'Tall spine' },
                'root feet':      { long: 'Both feet rooted, weight even',                             short: 'Even feet' },
            },
            exit: 'Release the mudra slowly.',
        },
        'Vrikshasana': {
            opening: ['Tree pose. Root one foot, find your gaze.'],
            holding: ['Sway is part of the pose. Breathe through it.'],
            cues: {
                'root feet':      { long: 'Spread the toes of the standing foot and press them down', short: 'Plant the standing foot' },
                'straighten leg': { long: 'Standing leg strong and straight, not locked',              short: 'Standing leg active' },
                'level hips':     { long: 'Keep both hips facing forward at the same height',          short: 'Hips square' },
                'open chest':     { long: 'Heart lifts, chest open, hands at heart or overhead',       short: 'Open the heart' },
                'soften gaze':    { long: 'Find a still point in front of you and stay with it',       short: 'Fix the gaze' },
                'lift chest':     { long: 'Sternum lifts away from the waist',                         short: 'Lift through the chest' },
            },
            exit: 'Release the foot gently. Try the other side.',
        },
        'Uttanasana': {
            opening: ['Standing Forward Fold. Hinge from the hips.'],
            holding: ['Let the head hang heavy. Breathe into the back.'],
            cues: {
                'lengthen spine': { long: 'Extend the spine forward first, then fold down',            short: 'Fold long, not round' },
                'bend knee deeper': { long: 'Soften the knees as much as you need for length',         short: 'Bend the knees' },
                'drop shoulders': { long: 'Shoulders release toward the floor, neck long',             short: 'Soft neck' },
                'root feet':      { long: 'Press into all four corners of the feet',                   short: 'Even in the feet' },
                'breathe':        { long: 'Long slow breaths into the back ribs',                      short: 'Breathe into the back' },
            },
            exit: 'Roll up slowly, head comes last.',
        },
        'Sukhasana': {
            opening: ['Easy Seat. Sit tall on your sit bones.'],
            holding: ['Let the hips open with time. Breath is the anchor.'],
            cues: {
                'lengthen spine': { long: 'Crown rises directly above the pelvis',                     short: 'Crown over hips' },
                'drop shoulders': { long: 'Shoulders soft, arms heavy, palms resting',                 short: 'Heavy arms' },
                'open chest':     { long: 'Subtle lift through the sternum, collarbones widen',        short: 'Heart open' },
                'breathe':        { long: 'Slow Ujjayi breath through the nose',                       short: 'Ujjayi breath' },
                'soften gaze':    { long: 'Eyes closed or soft, gaze inward',                          short: 'Gaze within' },
            },
            exit: 'Gently unwind the legs.',
        },
        'Dandasana': {
            opening: ['Staff Pose. Active legs, tall spine.'],
            holding: ['Think Tadasana sitting down.'],
            cues: {
                'straighten leg': { long: 'Legs fully extended, quads engaged, feet flexed',           short: 'Legs alive' },
                'flex foot':      { long: 'Flex the feet, toes point to the ceiling',                  short: 'Flex both feet' },
                'lengthen spine': { long: 'Sit up out of the waist, crown reaches up',                 short: 'Lift out of the waist' },
                'engage core':    { long: 'Low belly firm, supports the spine',                        short: 'Firm belly' },
                'drop shoulders': { long: 'Shoulder blades slide down the back',                       short: 'Shoulders down the back' },
            },
            exit: 'Release with a gentle fold.',
        },
        'Baddha Konasana': {
            opening: ['Bound Angle. Soles together, knees wide.'],
            holding: ['Let gravity do the work. Never force the knees.'],
            cues: {
                'level hips':     { long: 'Both sit bones pressing evenly into the floor',             short: 'Even sit bones' },
                'lengthen spine': { long: 'Spine long, crown rises as the knees fall wide',            short: 'Tall through the spine' },
                'open chest':     { long: 'Heart lifts, shoulders roll back and down',                 short: 'Heart forward' },
                'drop shoulders': { long: 'Shoulders slide down away from the ears',                   short: 'Shoulders soft' },
            },
            exit: 'Gently bring the knees together.',
        },
        'Paschimottanasana': {
            opening: ['Seated Forward Fold. Lead with the chest.'],
            holding: ['Breathe into the whole back body.'],
            cues: {
                'lengthen spine': { long: 'Fold from the hip creases, chest reaches over the legs',    short: 'Chest over legs' },
                'bend knee deeper': { long: 'Bend the knees if the low back rounds',                   short: 'Soften the knees' },
                'flex foot':      { long: 'Flex through the feet, reach into the heels',               short: 'Flex the feet' },
                'breathe':        { long: 'Use each exhale to fold a little deeper',                   short: 'Exhale to fold' },
                'drop shoulders': { long: 'Shoulders slide down, neck long',                           short: 'Soft neck' },
            },
            exit: 'Roll up one vertebra at a time.',
        },
        'Balasana': {
            opening: ['Child\u2019s Pose. Come home to the breath.'],
            holding: ['Let the body be heavy. Nothing to do.'],
            cues: {
                'lengthen spine': { long: 'Reach the hips toward the heels as the arms reach forward', short: 'Hips back, arms long' },
                'drop shoulders': { long: 'Soften the shoulders down into the mat',                    short: 'Shoulders to the mat' },
                'breathe':        { long: 'Breathe into the back ribs, slow and full',                 short: 'Breathe into the back' },
            },
            exit: 'Rise slowly, head last.',
        },
        // ─── INTERMEDIATE ────────────────────────────────────
        'Adho Mukha Svanasana': {
            opening: ['Downward Dog. Hips high, heart toward the thighs.'],
            holding: ['Pedal the heels if you need. Find your dog.'],
            cues: {
                'lift hips':      { long: 'Lift the sit bones up and back toward the ceiling',         short: 'Hips high' },
                'lengthen spine': { long: 'Spine is the priority — bend the knees to keep it long',    short: 'Long spine first' },
                'heels down':     { long: 'Melt the heels toward the floor, no need to touch',         short: 'Heels down' },
                'root feet':      { long: 'Hands press firmly, fingers spread wide',                   short: 'Press the palms' },
                'drop shoulders': { long: 'Shoulder blades slide down the back, away from the ears',   short: 'Shoulders away from ears' },
                'engage core':    { long: 'Low belly firm, ribs hug in',                               short: 'Hug the ribs in' },
            },
            exit: 'Gently lower to child\u2019s pose.',
        },
        'Virabhadrasana I': {
            opening: ['Warrior I. Strong legs, open heart.'],
            holding: ['Front thigh burns. Back heel grounded. Keep breathing.'],
            cues: {
                'knee over ankle':    { long: 'Stack the front knee directly over the front ankle',     short: 'Front knee over ankle' },
                'knee not past toes': { long: 'Front knee must not drift past the front toes',          short: 'Knee back, not past toes' },
                'square hips':        { long: 'Square both hip points toward the front of the mat',     short: 'Square the hips forward' },
                'straighten leg':     { long: 'Back leg straight, strong, back heel pressing down',     short: 'Back leg long' },
                'lift chest':         { long: 'Lift the chest, arms reach overhead',                    short: 'Lift the chest' },
                'reach overhead':     { long: 'Arms reach up, biceps by the ears',                      short: 'Arms up' },
                'root feet':          { long: 'Outer edge of the back foot pressing firmly',            short: 'Root the back foot' },
            },
            exit: 'Step back to mountain. Try the other side.',
        },
        'Virabhadrasana II': {
            opening: ['Warrior II. Gaze forward over the front hand.'],
            holding: ['Hips open wide. Front thigh works hard.'],
            cues: {
                'knee over ankle':    { long: 'Front knee stacks over the front ankle, tracking the second toe', short: 'Front knee over ankle' },
                'knee not past toes': { long: 'Keep the front shin vertical, never past the toes',              short: 'Knee back, shin vertical' },
                'extend arms':        { long: 'Arms reach in opposite directions, parallel to the floor',        short: 'Arms long and level' },
                'level hips':         { long: 'Both hips open to the long edge of the mat',                      short: 'Hips open wide' },
                'lift chest':         { long: 'Heart stays lifted, spine vertical',                              short: 'Chest tall' },
                'straighten leg':     { long: 'Back leg firm and straight, back foot grounded',                  short: 'Back leg strong' },
                'soften gaze':        { long: 'Gaze over the front fingertips, calm and steady',                  short: 'Gaze over the front hand' },
            },
            exit: 'Straighten the front leg and step back.',
        },
        'Utthita Trikonasana': {
            opening: ['Triangle pose. Front leg straight, reach long.'],
            holding: ['Think of two panes of glass on either side of you.'],
            cues: {
                'straighten leg':  { long: 'Front leg fully extended, micro-bend if the knee hyperextends',  short: 'Front leg straight' },
                'level hips':      { long: 'Top hip stacks over the bottom, hips in one plane',              short: 'Stack the top hip' },
                'lift chest':      { long: 'Top shoulder opens up, chest rolls toward the ceiling',          short: 'Chest to the ceiling' },
                'extend arms':     { long: 'Top arm reaches straight up, fingertips to the sky',             short: 'Top arm up' },
                'hand to block':   { long: 'Bottom hand on the shin or a block, not the knee',               short: 'Hand to the block' },
                'soften gaze':     { long: 'Gaze up at the top thumb if the neck allows',                    short: 'Gaze up' },
                'lengthen spine':  { long: 'Crown reaches away from the tailbone, spine in one line',         short: 'Reach through the crown' },
            },
            exit: 'Inhale up to stand. Switch sides.',
        },
        'Utkatasana': {
            opening: ['Chair pose. Sit low, lift tall.'],
            holding: ['Weight in the heels. Arms reach up.'],
            cues: {
                'bend knee deeper':  { long: 'Sink the hips lower, as if sitting into a chair',              short: 'Sit lower' },
                'knee not past toes': { long: 'Look down and check — knees should not cover the toes',        short: 'Knees behind the toes' },
                'engage core':        { long: 'Low belly firm, ribs hug in to support the low back',          short: 'Firm belly' },
                'reach overhead':     { long: 'Arms reach up, biceps hug the ears',                           short: 'Arms high' },
                'lift chest':         { long: 'Heart lifts even as the hips sink',                             short: 'Chest up as you sit' },
                'root feet':          { long: 'Weight stays in the heels, toes light',                         short: 'Heels heavy' },
            },
            exit: 'Straighten up. Shake the legs out.',
        },
        'Utthita Parsvakonasana': {
            opening: ['Extended Side Angle. One long line from heel to fingertip.'],
            holding: ['Side body reaches. Hips stay open.'],
            cues: {
                'knee over ankle':   { long: 'Front knee stacks over the front ankle at ninety degrees',      short: 'Front knee over ankle' },
                'extend arms':       { long: 'Top arm reaches over the ear, alongside the head',               short: 'Top arm over the ear' },
                'hand to block':     { long: 'Bottom hand or forearm on the thigh, floor, or block',            short: 'Bottom hand supported' },
                'straighten leg':    { long: 'Back leg straight, outer edge of the back foot pressing',         short: 'Back leg long' },
                'lift chest':        { long: 'Chest rolls open toward the ceiling',                             short: 'Chest to the sky' },
                'level hips':        { long: 'Hips open wide, not collapsed forward',                           short: 'Open through the hips' },
            },
            exit: 'Inhale up to stand. Other side.',
        },
        'Setu Bandhasana': {
            opening: ['Bridge Pose. Press the feet, lift the hips.'],
            holding: ['Shoulders beneath you. Chest to the chin.'],
            cues: {
                'lift hips':     { long: 'Drive the hips straight up, firm through the glutes',               short: 'Lift the hips' },
                'knees parallel': { long: 'Knees track straight over the ankles, not splaying out',            short: 'Knees parallel' },
                'open chest':     { long: 'Roll the shoulders under, clasp hands if possible',                 short: 'Shoulders under' },
                'root feet':      { long: 'Press into the feet evenly through all four corners',                short: 'Root the feet' },
                'engage core':    { long: 'Keep the low belly engaged to protect the lumbar',                   short: 'Belly engaged' },
            },
            exit: 'Lower the spine slowly, one vertebra at a time.',
        },
        // ─── ADVANCED ────────────────────────────────────────
        'Virabhadrasana III': {
            opening: ['Warrior III. Balance, strength, focus.'],
            holding: ['Back leg is a rudder. Arms like an arrow.'],
            cues: {
                'straighten leg':  { long: 'Standing leg strong, slight micro-bend at the knee',              short: 'Standing leg strong' },
                'level hips':      { long: 'Both hips face the floor, do not open the back hip',              short: 'Hips to the floor' },
                'extend arms':     { long: 'Arms reach forward, parallel to the floor',                        short: 'Arms forward' },
                'lengthen spine':  { long: 'Body in one long line from the back heel to the fingertips',       short: 'One long line' },
                'flex foot':       { long: 'Flex the back foot, toes point to the floor',                      short: 'Flex the back foot' },
                'engage core':     { long: 'Core firm, keeps the spine stable',                                 short: 'Core steady' },
                'soften gaze':     { long: 'Gaze slightly ahead of you on the floor',                           short: 'Gaze to the floor' },
            },
            exit: 'Step forward. Shake out the standing leg.',
        },
        'Ardha Chandrasana': {
            opening: ['Half Moon. Balance is the practice.'],
            holding: ['Top hip stacks. Top arm lifts. One long line.'],
            cues: {
                'straighten leg':  { long: 'Standing leg fully extended, foot firmly grounded',               short: 'Standing leg straight' },
                'level hips':      { long: 'Stack the top hip directly over the bottom hip',                   short: 'Stack the hips' },
                'extend arms':     { long: 'Top arm reaches straight up, bottom hand on a block',              short: 'Top arm up' },
                'hand to block':   { long: 'Bottom hand on a block — no need to reach the floor',              short: 'Hand on the block' },
                'flex foot':       { long: 'Flex the lifted foot, energy out through the heel',                short: 'Flex the top foot' },
                'lift chest':      { long: 'Top shoulder rolls up, chest opens to the ceiling',                short: 'Chest to the sky' },
            },
            exit: 'Float back to triangle, then rise.',
        },
        'Natarajasana': {
            opening: ['Dancer pose. An arc of breath and focus.'],
            holding: ['Kick the back foot into the hand to lift the chest.'],
            cues: {
                'straighten leg':  { long: 'Standing leg strong and long, micro-bend if needed',              short: 'Standing leg strong' },
                'lift chest':      { long: 'Kick the back foot into the hand to arc the chest open',           short: 'Kick to lift' },
                'open chest':      { long: 'Front arm reaches forward as the chest arcs up and open',          short: 'Heart opens forward' },
                'level hips':      { long: 'Keep both hips facing forward even as the back leg lifts',         short: 'Hips square' },
                'soften gaze':     { long: 'Soft gaze on a still point in front of you',                        short: 'Fix the gaze' },
                'extend arms':     { long: 'Front arm reaches long, fingertips away',                           short: 'Front arm long' },
            },
            exit: 'Release the foot slowly. Try the other side.',
        },
    };

    /**
     * Rewrite a correction's message and shortMessage for the current pose.
     * Returns a NEW correction object (non-mutating). If no pose-specific cue
     * exists, returns the original correction unchanged.
     */
    function personalise(correction, poseName) {
        if (!correction || !correction.message || !poseName) return correction;
        const pose = POSE_CUES[poseName];
        if (!pose || !pose.cues) return correction;
        const key = _matchKey(correction.message);
        if (!key) return correction;
        const rewrite = pose.cues[key];
        if (!rewrite) return correction;
        return {
            ...correction,
            message: rewrite.long || correction.message,
            shortMessage: rewrite.short || correction.shortMessage || rewrite.long,
        };
    }

    /** Get the opening line(s) for a pose, or null. */
    function opening(poseName) {
        const p = POSE_CUES[poseName];
        if (!p || !p.opening || !p.opening.length) return null;
        return p.opening[Math.floor(Math.random() * p.opening.length)];
    }

    /** Get a "holding well" line for a pose, rotated randomly, or null. */
    function holding(poseName) {
        const p = POSE_CUES[poseName];
        if (!p || !p.holding || !p.holding.length) return null;
        return p.holding[Math.floor(Math.random() * p.holding.length)];
    }

    /** Get the exit line for a pose, or null. */
    function exit(poseName) {
        const p = POSE_CUES[poseName];
        return (p && p.exit) ? p.exit : null;
    }

    window.PoseCues = { POSE_CUES, personalise, opening, holding, exit };
})();
