/*
 * Sunday · AsanaMind — 6-semester Course Plan + Quiz Bank
 *
 * Six structured courses, one per semester from Sem 3 through Sem 8.
 * Each course is a 6-month window that opens (a) by date, calculated
 * from the user's registration date, and (b) by sequence — the previous
 * course must be completed first.
 *
 * Each course holds a slice of the 20-pose ASANA_LIBRARY. For every
 * pose, the learner must:
 *   1. Hold the pose at ≥90% alignment for 10 continuous seconds in AR
 *      (best of 3 attempts is recorded as the AR mark).
 *   2. Pass a 3-question quiz drawn from this file (≥2/3 correct).
 *
 * A pose is "passed" only when both AR and quiz pass. The pose mark is
 * the average of the AR and quiz percentages. The course mark is the
 * average of all pose marks. Marks appear on the certificate.
 *
 * Public globals:
 *   window.SUNDAY_COURSES   — array of 6 course definitions
 *   window.QUIZ_BANK        — pose-name → array of 3 quiz questions
 *   window.CourseUtils      — helper functions for date/status logic
 */
(function () {
    'use strict';

    // ─────────────────────────────────────────────────────────────
    // 6 SEMESTER COURSES
    // ─────────────────────────────────────────────────────────────
    const SUNDAY_COURSES = [
        {
            id: 'sem3',
            semesterNumber: 3,
            name: 'Foundations',
            title: 'Semester 3 — Foundations',
            tagline: 'Where every yoga journey begins.',
            description: 'Stand still, breathe deep, root down. Four asanas that teach the body what every other pose will ask of it: alignment, breath and steady gaze.',
            color: '#0F3D2E',
            accent: '#E0A23F',
            icon: '⛰️',
            durationMonths: 6,
            poses: ['Tadasana', 'Urdhva Hastasana', 'Anjali Mudra', 'Vrikshasana'],
        },
        {
            id: 'sem4',
            semesterNumber: 4,
            name: 'Grounding',
            title: 'Semester 4 — Grounding',
            tagline: 'Sit, fold, return.',
            description: 'The seated foundation. Three asanas that meet the floor and teach the body to lengthen along its own axis.',
            color: '#1F5A44',
            accent: '#E0A23F',
            icon: '🌿',
            durationMonths: 6,
            poses: ['Uttanasana', 'Sukhasana', 'Dandasana'],
        },
        {
            id: 'sem5',
            semesterNumber: 5,
            name: 'Restoration',
            title: 'Semester 5 — Restoration',
            tagline: 'Open, soften, breathe.',
            description: 'Hip openers and forward folds. The slow medicine of yoga — the asanas that ask for time and reward with stillness.',
            color: '#6FA089',
            accent: '#C2552F',
            icon: '🪷',
            durationMonths: 6,
            poses: ['Baddha Konasana', 'Paschimottanasana', 'Balasana'],
        },
        {
            id: 'sem6',
            semesterNumber: 6,
            name: 'Strength',
            title: 'Semester 6 — Strength',
            tagline: 'Earn your warrior.',
            description: 'The first standing strength asanas. Where stamina, focus and willpower meet on the mat.',
            color: '#C2552F',
            accent: '#F3D58C',
            icon: '⚔️',
            durationMonths: 6,
            poses: ['Adho Mukha Svanasana', 'Virabhadrasana I', 'Virabhadrasana II'],
        },
        {
            id: 'sem7',
            semesterNumber: 7,
            name: 'Lateral Body',
            title: 'Semester 7 — Lateral Body',
            tagline: 'The side body, awakened.',
            description: 'Triangle, side angle, chair, bridge. Four asanas that train the planes of the body most ignored by everyday life.',
            color: '#0F3D2E',
            accent: '#F3D58C',
            icon: '📐',
            durationMonths: 6,
            poses: ['Utthita Trikonasana', 'Utkatasana', 'Utthita Parsvakonasana', 'Setu Bandhasana'],
        },
        {
            id: 'sem8',
            semesterNumber: 8,
            name: 'Mastery',
            title: 'Semester 8 — Mastery',
            tagline: 'The graduate practice.',
            description: 'Three advanced standing asanas — Warrior III, Half Moon, Dancer. Balance, grace, the dance of breath and form.',
            color: '#14120E',
            accent: '#E0A23F',
            icon: '🏆',
            durationMonths: 6,
            poses: ['Virabhadrasana III', 'Ardha Chandrasana', 'Natarajasana'],
        },
    ];

    // ─────────────────────────────────────────────────────────────
    // QUIZ BANK — 3 questions per pose, 60 questions total.
    // Each question:
    //   q        — the question
    //   options  — 4 multiple-choice answers
    //   correct  — index (0-3) of the correct answer
    //   why      — short explanation shown after answering
    //   topic    — which PoseNote field this draws from
    // ─────────────────────────────────────────────────────────────
    const QUIZ_BANK = {
        // ─── BEGINNER ────────────────────────────────────────
        'Tadasana': [
            {
                q: 'What does the Sanskrit name "Tadasana" translate to?',
                options: ['Tree Pose', 'Mountain Pose', 'Warrior Pose', 'Bridge Pose'],
                correct: 1,
                why: 'Tada means mountain, asana means seat. The pose of a still, immovable mountain.',
                topic: 'meaning',
            },
            {
                q: 'Which of these is the most common mistake in Tadasana?',
                options: [
                    'Lifting the crown of the head',
                    'Distributing weight evenly through both feet',
                    'Locking the knees backward into hyperextension',
                    'Engaging the thighs',
                ],
                correct: 2,
                why: 'Locking the knees jams the joint and dumps the pelvis forward — keep a micro-engagement instead.',
                topic: 'commonMistakes',
            },
            {
                q: 'Tadasana is best described as the foundation for which group of asanas?',
                options: [
                    'All seated forward folds',
                    'Every standing asana',
                    'Backbends only',
                    'Inversions only',
                ],
                correct: 1,
                why: 'Every standing asana begins from Tadasana — it teaches the body the alignment all the others rely on.',
                topic: 'benefitsList',
            },
        ],
        'Urdhva Hastasana': [
            {
                q: 'Urdhva Hastasana translates to:',
                options: ['Downward Hand Pose', 'Upward Salute', 'Side Stretch Pose', 'Seated Tall Pose'],
                correct: 1,
                why: 'Urdhva means upward, hasta means hand. The upward salute that opens the day.',
                topic: 'meaning',
            },
            {
                q: 'A common mistake in Upward Salute is:',
                options: [
                    'Reaching the fingertips up',
                    'Rooting through the feet',
                    'Shrugging the shoulders up to the ears',
                    'Keeping the spine long',
                ],
                correct: 2,
                why: 'Shoulders should slide down the back even as the arms reach up — strength and softness at once.',
                topic: 'commonMistakes',
            },
            {
                q: 'Which body parts does Urdhva Hastasana primarily target?',
                options: [
                    'Wrists and forearms only',
                    'Quadriceps and hamstrings',
                    'Shoulders, side body and spine',
                    'Hip flexors only',
                ],
                correct: 2,
                why: 'It opens the entire upper body — shoulders, side body and spine — while the legs stay rooted.',
                topic: 'targetedList',
            },
        ],
        'Anjali Mudra': [
            {
                q: 'What does "Anjali Mudra" mean?',
                options: ['Standing Seal', 'Offering Seal', 'Strength Seal', 'Sleep Seal'],
                correct: 1,
                why: 'Anjali means offering, mudra means seal — the gesture of honouring.',
                topic: 'meaning',
            },
            {
                q: 'Where do the thumbs touch in Anjali Mudra?',
                options: ['The forehead', 'The navel', 'The sternum', 'The chin'],
                correct: 2,
                why: 'The thumbs rest at the sternum, drawing awareness to the heart center.',
                topic: 'instructions',
            },
            {
                q: 'Which energy center does Anjali Mudra primarily honour?',
                options: ['Root chakra', 'Heart chakra (Anahata)', 'Crown chakra', 'Solar plexus'],
                correct: 1,
                why: 'Anjali Mudra is the gesture of devotion and gratitude, centred at the heart.',
                topic: 'chakra',
            },
        ],
        'Vrikshasana': [
            {
                q: 'Vrikshasana means:',
                options: ['Tree Pose', 'Lotus Pose', 'Flame Pose', 'Eagle Pose'],
                correct: 0,
                why: 'Vriksha means tree — the pose of a strong, swaying, rooted tree.',
                topic: 'meaning',
            },
            {
                q: 'Where should the raised foot NEVER be placed?',
                options: [
                    'On the inner calf',
                    'On the inner thigh',
                    'Directly on the standing knee',
                    'On the ankle with toes down',
                ],
                correct: 2,
                why: 'Pressing on the knee joint creates lateral stress. Always above or below the knee.',
                topic: 'commonMistakes',
            },
            {
                q: 'Which is the primary skill Tree Pose develops?',
                options: [
                    'Hamstring flexibility',
                    'Inversions',
                    'Balance and concentration',
                    'Backbending',
                ],
                correct: 2,
                why: 'Tree Pose builds balance and the steady gaze (drishti) that train calm, alert focus.',
                topic: 'benefitsList',
            },
        ],
        'Uttanasana': [
            {
                q: 'Uttanasana translates to:',
                options: [
                    'Standing Forward Fold (intense back-body stretch)',
                    'Seated Twist',
                    'Backbend Pose',
                    'Reclining Hero',
                ],
                correct: 0,
                why: 'Ut means intense, tan means stretch — the intense stretch of the back body.',
                topic: 'meaning',
            },
            {
                q: 'In Uttanasana, the fold should hinge from:',
                options: ['The waist', 'The neck', 'The hip joints', 'The knees'],
                correct: 2,
                why: 'Hinge from the hip crease, not the waist — this protects the spine and opens the hamstrings.',
                topic: 'instructions',
            },
            {
                q: 'Which is a common Uttanasana mistake?',
                options: [
                    'Bending the knees generously',
                    'Letting the head hang heavy',
                    'Rounding the low back to force the hands down',
                    'Folding from the hip joints',
                ],
                correct: 2,
                why: 'Length over depth — a bent-knee fold with a long spine beats a rounded fold every time.',
                topic: 'commonMistakes',
            },
        ],
        'Sukhasana': [
            {
                q: 'Sukhasana means:',
                options: ['Difficult Seat', 'Easy / Comfortable Seat', 'Royal Seat', 'Strong Seat'],
                correct: 1,
                why: 'Sukha means ease, comfort. The simple seat that serves practice without theatrics.',
                topic: 'meaning',
            },
            {
                q: 'If your knees float higher than the hips in Sukhasana, what should you do?',
                options: [
                    'Force the knees down with the hands',
                    'Sit on a folded blanket or cushion to elevate the hips',
                    'Skip the pose entirely',
                    'Hunch the shoulders to compensate',
                ],
                correct: 1,
                why: 'Adding height under the hips lets the pelvis tilt forward and the spine stay long.',
                topic: 'modifications',
            },
            {
                q: 'Sukhasana is most often used as the foundation for:',
                options: [
                    'Backbends',
                    'Inversions',
                    'Pranayama (breathwork) and meditation',
                    'Power yoga sequences',
                ],
                correct: 2,
                why: 'It is the seat used for breathwork and meditation — ease in the body lets the mind rest.',
                topic: 'benefitsList',
            },
        ],
        'Dandasana': [
            {
                q: 'Dandasana translates to:',
                options: ['Spider Pose', 'Boat Pose', 'Staff Pose', 'Sword Pose'],
                correct: 2,
                why: 'Danda means staff or stick — the seated equivalent of Tadasana.',
                topic: 'meaning',
            },
            {
                q: 'In Dandasana, the feet are:',
                options: [
                    'Pointed away from the body',
                    'Flexed back toward the face, toes to the ceiling',
                    'Crossed at the ankles',
                    'Resting on a block',
                ],
                correct: 1,
                why: 'Active feet — flexed and energised — are the seated equivalent of grounded feet in Tadasana.',
                topic: 'instructions',
            },
            {
                q: 'Dandasana is most therapeutic for:',
                options: [
                    'Relieving migraines',
                    'Building grip strength',
                    'Improving posture for desk-bound bodies',
                    'Increasing leg flexibility only',
                ],
                correct: 2,
                why: 'It rebuilds spinal extensors that atrophy from chronic chair sitting — direct medicine for tech kyphosis.',
                topic: 'benefitsList',
            },
        ],
        'Baddha Konasana': [
            {
                q: 'Baddha Konasana means:',
                options: ['Bound Angle Pose', 'Free Angle Pose', 'Seated Twist', 'Folded Heart Pose'],
                correct: 0,
                why: 'Baddha means bound, kona means angle — the bound angle of the legs.',
                topic: 'meaning',
            },
            {
                q: 'In Baddha Konasana, what should you NEVER do?',
                options: [
                    'Lengthen the spine upward',
                    'Force the knees down with the hands or elbows',
                    'Hold the feet or ankles',
                    'Fold forward gently',
                ],
                correct: 1,
                why: 'Forcing the knees risks injury. Use blocks or cushions and let the hips open over time.',
                topic: 'commonMistakes',
            },
            {
                q: 'Which area benefits most from regular Baddha Konasana practice?',
                options: [
                    'Wrists and elbows',
                    'Inner thighs, groins and hips',
                    'Calves and ankles',
                    'Cervical spine',
                ],
                correct: 1,
                why: 'It opens the inner thighs, groins and the hip joints — critical for sedentary bodies.',
                topic: 'benefitsList',
            },
        ],
        'Paschimottanasana': [
            {
                q: '"Paschima" in Paschimottanasana refers to:',
                options: [
                    'The east, the front body',
                    'The west, the back body',
                    'The sky, the upper body',
                    'The earth, the lower body',
                ],
                correct: 1,
                why: 'Paschima means west — in yogic geography, the back of the body.',
                topic: 'meaning',
            },
            {
                q: 'In Seated Forward Fold, the priority is:',
                options: [
                    'Touching the toes at all costs',
                    'Length in the spine — chest reaches forward, not down',
                    'Bouncing to deepen the stretch',
                    'Holding the breath in depth',
                ],
                correct: 1,
                why: 'Reach the chest forward with a long spine. Depth is the by-product of length, not the goal.',
                topic: 'commonMistakes',
            },
            {
                q: 'A primary nervous-system effect of Paschimottanasana is:',
                options: [
                    'Increased adrenaline',
                    'Calming the nervous system, easing mild depression',
                    'Stimulating the sympathetic response',
                    'Sharp mental alertness',
                ],
                correct: 1,
                why: 'Sustained passive flexion lengthens the back fascia and triggers parasympathetic recovery.',
                topic: 'benefitsList',
            },
        ],
        'Balasana': [
            {
                q: 'Balasana means:',
                options: ['Warrior Pose', 'Child\u2019s Pose', 'Eagle Pose', 'Hero Pose'],
                correct: 1,
                why: 'Bala means child — the pose of return.',
                topic: 'meaning',
            },
            {
                q: 'Balasana is best used:',
                options: [
                    'As a warm-up only',
                    'Only at the end of practice',
                    'As a resting pose between stronger asanas',
                    'Never — it is just relaxation',
                ],
                correct: 2,
                why: 'It is the pose of return. Use it whenever practice gets intense and breath gets short.',
                topic: 'benefitsList',
            },
            {
                q: 'If your forehead does not reach the floor in Child\u2019s Pose, you should:',
                options: [
                    'Force the head down anyway',
                    'Skip the pose entirely',
                    'Stack the fists or use a block under the forehead',
                    'Lift the hips off the heels and forget the fold',
                ],
                correct: 2,
                why: 'A supported forehead lets the neck release fully — the most important part of the pose.',
                topic: 'modifications',
            },
        ],

        // ─── INTERMEDIATE ────────────────────────────────────
        'Adho Mukha Svanasana': [
            {
                q: 'Adho Mukha Svanasana literally translates to:',
                options: [
                    'Upward-Facing Dog',
                    'Downward-Facing Dog',
                    'Side-Facing Cat',
                    'Standing Bear',
                ],
                correct: 1,
                why: 'Adho mukha means face down, svana means dog — the face-down dog stretch.',
                topic: 'meaning',
            },
            {
                q: 'In Down Dog, the highest point of the body should be:',
                options: ['The head', 'The knees', 'The hips', 'The wrists'],
                correct: 2,
                why: 'It is a hip-lift pose. Hips up and back, spine long — bend the knees if needed.',
                topic: 'alignmentChecks',
            },
            {
                q: 'For a student with carpal tunnel syndrome, the modification is to:',
                options: [
                    'Push harder through the wrists',
                    'Practise on the forearms (Dolphin Pose)',
                    'Avoid bending the knees',
                    'Lift the hands off the floor',
                ],
                correct: 1,
                why: 'Dolphin Pose on the forearms gives the same shape without loading the wrists.',
                topic: 'modifications',
            },
        ],
        'Virabhadrasana I': [
            {
                q: 'Virabhadra was:',
                options: [
                    'A river goddess',
                    'A fierce mythological warrior',
                    'A meditation teacher',
                    'A flower deity',
                ],
                correct: 1,
                why: 'Virabhadra is the fierce warrior of Hindu myth — Warrior I is named for him.',
                topic: 'meaning',
            },
            {
                q: 'In Warrior I, the front knee should be:',
                options: [
                    'Past the toes for a deeper stretch',
                    'Stacked directly over the front ankle',
                    'Behind the heel',
                    'Locked straight',
                ],
                correct: 1,
                why: 'Front knee over front ankle — protects the joint and creates the right shape for the leg.',
                topic: 'alignmentChecks',
            },
            {
                q: 'The hips in Warrior I should be:',
                options: [
                    'Open to the long edge of the mat',
                    'Square toward the front of the mat',
                    'Tilted to one side',
                    'Position does not matter',
                ],
                correct: 1,
                why: 'Square hips forward distinguishes Warrior I from Warrior II (which faces sideways).',
                topic: 'commonMistakes',
            },
        ],
        'Virabhadrasana II': [
            {
                q: 'Warrior II is the pose of:',
                options: [
                    'Eyes forward, present, ready',
                    'Eyes closed, surrender',
                    'Eyes up, devotion',
                    'Eyes down, restraint',
                ],
                correct: 0,
                why: 'The second warrior — eyes forward over the front fingers, present and ready.',
                topic: 'meaning',
            },
            {
                q: 'In Warrior II, the front thigh works to be:',
                options: [
                    'Vertical to the floor',
                    'Parallel to the floor',
                    'Lifted high above the hip',
                    'Crossed over the back leg',
                ],
                correct: 1,
                why: 'Front thigh parallel to the floor — that is the warrior\u2019s deep, stable stance.',
                topic: 'alignmentChecks',
            },
            {
                q: 'Warrior II primarily builds:',
                options: [
                    'Inversion strength',
                    'Stamina, focus and leg power',
                    'Wrist flexibility',
                    'Backbend depth',
                ],
                correct: 1,
                why: 'Sustained quadriceps and hip-rotator engagement under a steady gaze trains real stamina.',
                topic: 'benefitsList',
            },
        ],
        'Utthita Trikonasana': [
            {
                q: '"Trikona" in Utthita Trikonasana means:',
                options: ['Square', 'Triangle', 'Circle', 'Diamond'],
                correct: 1,
                why: 'Tri-kona means triangle — the pose builds three triangles between the legs, arms and torso.',
                topic: 'meaning',
            },
            {
                q: 'In Triangle Pose, the bottom hand should rest:',
                options: [
                    'Directly on the knee joint',
                    'On the shin, ankle, or a block',
                    'On the floor only — props are cheating',
                    'On the front foot',
                ],
                correct: 1,
                why: 'Never on the knee joint. The shin, ankle or a block protects the joint and lets the chest stay open.',
                topic: 'commonMistakes',
            },
            {
                q: 'The most common Triangle mistake is:',
                options: [
                    'Reaching the top arm too high',
                    'Stacking the shoulders',
                    'Collapsing the chest toward the floor',
                    'Looking up at the top hand',
                ],
                correct: 2,
                why: 'Triangle is two parallel planes — chest forward, hips back. Never collapse forward over the leg.',
                topic: 'commonMistakes',
            },
        ],
        'Utkatasana': [
            {
                q: '"Utkata" in Utkatasana means:',
                options: ['Gentle', 'Powerful, fierce', 'Wide', 'Empty'],
                correct: 1,
                why: 'Utkata means powerful, fierce — often called Chair Pose, but the Sanskrit suggests intensity.',
                topic: 'meaning',
            },
            {
                q: 'In Chair Pose, where should the weight be?',
                options: [
                    'In the toes, heels lifted',
                    'In the heels, toes light',
                    'Evenly between hands and feet',
                    'On the front of the knees',
                ],
                correct: 1,
                why: 'Weight in the heels lets the quads engage cleanly without the knees drifting past the toes.',
                topic: 'alignmentChecks',
            },
            {
                q: 'A common Chair Pose mistake is:',
                options: [
                    'Sitting too low',
                    'Reaching the arms up',
                    'Letting the knees drift past the toes',
                    'Drawing the navel in',
                ],
                correct: 2,
                why: 'Knees past toes overloads the joint. Weight stays in the heels, knees track behind the toes.',
                topic: 'commonMistakes',
            },
        ],
        'Utthita Parsvakonasana': [
            {
                q: 'Utthita Parsvakonasana translates to:',
                options: [
                    'Twisted Crow Pose',
                    'Extended Side Angle',
                    'Reclining Eagle',
                    'Bound Half Lotus',
                ],
                correct: 1,
                why: 'Utthita means extended, parsva is side, kona is angle — extended side angle.',
                topic: 'meaning',
            },
            {
                q: 'The signature line in Side Angle goes from:',
                options: [
                    'Wrist to wrist',
                    'Head to feet',
                    'Back heel to top fingertips',
                    'Front knee to front shoulder',
                ],
                correct: 2,
                why: 'One long diagonal line — back heel to top fingertips — is the heart of the pose.',
                topic: 'alignmentChecks',
            },
            {
                q: 'If a student\u2019s torso collapses forward, they should:',
                options: [
                    'Push harder through the front leg',
                    'Use a block under the bottom hand for support',
                    'Skip the pose',
                    'Hold the breath',
                ],
                correct: 1,
                why: 'A block under the bottom hand restores length so the chest can rotate up where it belongs.',
                topic: 'modifications',
            },
        ],
        'Setu Bandhasana': [
            {
                q: 'Setu Bandhasana means:',
                options: [
                    'Bridge construction',
                    'Cobra rising',
                    'Wheel of life',
                    'Boat in motion',
                ],
                correct: 0,
                why: 'Setu bandha — bridge construction. The bridge between earth and sky.',
                topic: 'meaning',
            },
            {
                q: 'In Bridge Pose, the knees should be:',
                options: [
                    'Splaying wide',
                    'Parallel, hip-width apart, tracking over the heels',
                    'Squeezed together',
                    'Past the toes',
                ],
                correct: 1,
                why: 'Knees parallel and over the heels protects the joints and engages the inner thighs cleanly.',
                topic: 'alignmentChecks',
            },
            {
                q: 'Which is the most common Bridge Pose mistake?',
                options: [
                    'Pressing the feet into the mat',
                    'Crunching the back of the neck',
                    'Engaging the glutes',
                    'Lifting the chest',
                ],
                correct: 1,
                why: 'The chin should not press to the chest — lift the chest to the chin instead, keeping neck soft.',
                topic: 'commonMistakes',
            },
        ],

        // ─── ADVANCED ────────────────────────────────────────
        'Virabhadrasana III': [
            {
                q: 'Warrior III is the warrior of:',
                options: ['Twist', 'Flight', 'Surrender', 'Inversion'],
                correct: 1,
                why: 'The warrior in flight — body and lifted leg parallel to the floor like an arrow.',
                topic: 'meaning',
            },
            {
                q: 'In Warrior III, the lifted hip should:',
                options: [
                    'Open up toward the ceiling',
                    'Rotate down to face the floor',
                    'Bend at 90 degrees',
                    'Position does not matter',
                ],
                correct: 1,
                why: 'Both hips face the floor — opening the back hip is the most common mistake in this pose.',
                topic: 'alignmentChecks',
            },
            {
                q: 'A balance challenge in Warrior III makes you stronger because:',
                options: [
                    'It works only the upper body',
                    'It recruits the gluteus medius and ankle stabilisers in concert',
                    'It is purely cardiovascular',
                    'It stretches the hamstrings only',
                ],
                correct: 1,
                why: 'Single-leg dynamic balance trains the small stabilising muscles that prevent falls and back pain.',
                topic: 'science',
            },
        ],
        'Ardha Chandrasana': [
            {
                q: '"Ardha Chandra" means:',
                options: [
                    'Half Moon',
                    'Full Sun',
                    'Crescent Wave',
                    'Quarter Star',
                ],
                correct: 0,
                why: 'Ardha is half, chandra is moon — the half moon balance.',
                topic: 'meaning',
            },
            {
                q: 'In Half Moon, the hips should be:',
                options: [
                    'Stacked vertically',
                    'Open horizontally',
                    'Tilted forward',
                    'Position does not matter',
                ],
                correct: 0,
                why: 'Stack the top hip directly over the bottom — without it the pose has no shape.',
                topic: 'alignmentChecks',
            },
            {
                q: 'Most students in Ardha Chandrasana benefit from:',
                options: [
                    'Forcing the bottom hand to the floor',
                    'A block under the bottom hand for vertical alignment',
                    'Holding only with the top arm',
                    'Closing the eyes for balance',
                ],
                correct: 1,
                why: 'A block restores height — the body can stack vertically instead of leaning forward.',
                topic: 'modifications',
            },
        ],
        'Natarajasana': [
            {
                q: 'Nataraja is the:',
                options: [
                    'Cosmic dancer (Shiva)',
                    'River goddess',
                    'Moon deity',
                    'Tree spirit',
                ],
                correct: 0,
                why: 'Nataraja is Shiva, the cosmic dancer — Dancer Pose embodies that grace and balance.',
                topic: 'meaning',
            },
            {
                q: 'In Dancer Pose, the chest lifts because:',
                options: [
                    'The arms pull the chest up',
                    'The back foot kicks into the hand',
                    'The standing leg straightens',
                    'The breath is held',
                ],
                correct: 1,
                why: 'The kick of the back foot into the hand creates the chest lift — push, not pull.',
                topic: 'beginnerTip',
            },
            {
                q: 'Why does Dancer Pose help desk workers in particular?',
                options: [
                    'It works only the wrists',
                    'It stretches the rectus femoris and chronic hip-flexor tightness from sitting',
                    'It builds shoulder strength',
                    'It improves grip',
                ],
                correct: 1,
                why: 'Hip extension in this pose lengthens the very tissues that shorten from chronic chair sitting.',
                topic: 'science',
            },
        ],
    };

    // ─────────────────────────────────────────────────────────────
    // CourseUtils — date / status helpers
    // ─────────────────────────────────────────────────────────────
    const COURSE_START_KEY = 'sundayCourseStartDate';
    const DEFAULT_DEMO_START = '2025-01-01T00:00:00.000Z';

    function getCourseStartDate() {
        let raw = null;
        try { raw = localStorage.getItem(COURSE_START_KEY); } catch (_) {}
        if (!raw) {
            // Demo default: 1 Jan 2025 so timeline windows have already opened.
            raw = DEFAULT_DEMO_START;
            try { localStorage.setItem(COURSE_START_KEY, raw); } catch (_) {}
        }
        return new Date(raw);
    }

    function setCourseStartDate(date) {
        try { localStorage.setItem(COURSE_START_KEY, new Date(date).toISOString()); } catch (_) {}
    }

    /** Add `months` calendar months to a Date (preserves day-of-month when possible). */
    function addMonths(date, months) {
        const d = new Date(date);
        const targetMonth = d.getMonth() + months;
        d.setMonth(targetMonth);
        return d;
    }

    /** Window for a course: { opensAt, closesAt }. Each course is 6 months long. */
    function getCourseWindow(courseId) {
        const idx = SUNDAY_COURSES.findIndex(c => c.id === courseId);
        if (idx < 0) return null;
        const start = getCourseStartDate();
        const opensAt = addMonths(start, idx * 6);
        const closesAt = addMonths(opensAt, 6);
        return { opensAt, closesAt };
    }

    function isCourseDateUnlocked(courseId) {
        const w = getCourseWindow(courseId);
        if (!w) return false;
        return new Date() >= w.opensAt;
    }

    /** Sequence: course N is sequence-unlocked iff course N-1 is fully completed. */
    function isCourseSequenceUnlocked(courseId, progress) {
        const idx = SUNDAY_COURSES.findIndex(c => c.id === courseId);
        if (idx <= 0) return true;
        const prev = SUNDAY_COURSES[idx - 1];
        const prevProg = progress.courses[prev.id];
        return !!(prevProg && prevProg.completed);
    }

    /**
     * Status: 'locked-date' | 'locked-sequence' | 'available' | 'in-progress' | 'completed'
     */
    function getCourseStatus(courseId, progress) {
        const cp = progress.courses[courseId];
        if (cp && cp.completed) return 'completed';
        if (!isCourseDateUnlocked(courseId)) return 'locked-date';
        if (!isCourseSequenceUnlocked(courseId, progress)) return 'locked-sequence';
        const anyStarted = cp && cp.poses && cp.poses.some(p => p.arAttempts > 0 || p.quizAttempts > 0);
        return anyStarted ? 'in-progress' : 'available';
    }

    /** Build a fresh progress record for a course from its definition. */
    function freshCourseProgress(course) {
        return {
            id: course.id,
            poses: course.poses.map((name, i) => ({
                name,
                locked: i !== 0,           // unlock one at a time within the course
                arAttempts: 0,
                arBest: 0,
                arPassed: false,
                quizAttempts: 0,
                quizBest: 0,
                quizPassed: false,
                completed: false,
                finalScore: 0,
                completedAt: null,
            })),
            startedAt: null,
            completedAt: null,
            completed: false,
            certificateEarned: false,
            finalScore: 0,
        };
    }

    /** Build the empty top-level progress object — used on first run / migration. */
    function freshProgress() {
        const courses = {};
        for (const c of SUNDAY_COURSES) courses[c.id] = freshCourseProgress(c);
        return { schemaVersion: 2, courses };
    }

    /** Compute pose mark = mean(arBest, quizBest), rounded. */
    function poseMark(poseProg) {
        if (!poseProg) return 0;
        const ar = poseProg.arBest || 0;
        const quiz = poseProg.quizBest || 0;
        if (!poseProg.arPassed && !poseProg.quizPassed) return 0;
        return Math.round((ar + quiz) / 2);
    }

    /** Course mark = mean of completed pose marks. */
    function courseMark(courseProg) {
        if (!courseProg || !courseProg.poses) return 0;
        const completed = courseProg.poses.filter(p => p.completed);
        if (!completed.length) return 0;
        const total = completed.reduce((s, p) => s + (p.finalScore || poseMark(p)), 0);
        return Math.round(total / completed.length);
    }

    /** Master mark = mean of completed course marks. */
    function masterMark(progress) {
        const done = SUNDAY_COURSES.map(c => progress.courses[c.id]).filter(cp => cp && cp.completed);
        if (!done.length) return 0;
        const total = done.reduce((s, cp) => s + (cp.finalScore || courseMark(cp)), 0);
        return Math.round(total / done.length);
    }

    function pickQuizForPose(poseName) {
        return QUIZ_BANK[poseName] || [];
    }

    window.SUNDAY_COURSES = SUNDAY_COURSES;
    window.QUIZ_BANK = QUIZ_BANK;
    window.CourseUtils = {
        getCourseStartDate,
        setCourseStartDate,
        getCourseWindow,
        isCourseDateUnlocked,
        isCourseSequenceUnlocked,
        getCourseStatus,
        freshCourseProgress,
        freshProgress,
        poseMark,
        courseMark,
        masterMark,
        pickQuizForPose,
        addMonths,
        DEFAULT_DEMO_START,
    };
})();
