/*
 * Sunday · AsanMinds — Organization helpers (frontend)
 *
 * Tiny shared utilities used by both the super-admin org tab and the
 * org-admin SPA. No external deps.
 */
(function () {
    'use strict';

    /**
     * Compute current semester from a 4-digit batch year + today's date.
     * 6-month sems, July-start convention.
     *   2023 batch joined July 2023.
     *   Nov 2023  → sem 1
     *   Jan 2024  → sem 2  (Jan-June half)
     *   Aug 2024  → sem 3
     *   ...
     *   Sept 2026 → sem 7
     */
    function currentSemester(batch, now) {
        const y = parseInt(batch, 10);
        if (!y || isNaN(y)) return 0;
        const today = now || new Date();
        const yearDiff = today.getFullYear() - y;
        // July-start (month index 6); before July still in odd-numbered sem.
        const inSecondHalf = today.getMonth() >= 6;
        // Sem 1 = first half of joining year (July onward of joining year)
        // Each yearDiff = 2 sems
        let sem = yearDiff * 2 + (inSecondHalf ? 1 : 2);
        // For students yet to start (joined this July, but it's still Apr-Jun)
        if (sem < 1) sem = 0;
        // Clamp to 8 (a B.E./B.Tech is 8 sems)
        if (sem > 8) sem = 8;
        return sem;
    }

    /** Strip and normalise an email — used everywhere a user types one. */
    function normEmail(s) {
        return (s || '').trim().toLowerCase();
    }

    /** Pretty short label for a student row: 4VV23CI001 · A or 2023 CSE-AIML A. */
    function academicLabel(a) {
        if (!a) return '';
        if (a.usn) return a.usn + (a.section ? ' · ' + a.section : '');
        const bits = [a.batch, a.branch, a.section].filter(Boolean);
        return bits.join(' ');
    }

    window.OrgHelpers = {
        currentSemester,
        normEmail,
        academicLabel,
    };
})();
