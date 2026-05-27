# Bugfix Implementation Plan

Tasks map to the bug conditions in `bugfix.md`. Most of the code surface (the
`/api/assistant` proxy with `YOGA_FALLBACKS`, the rewritten voice `onresult`
handler, and the `showReferenceOverlay` method) already landed in an earlier
session; this plan closes the remaining gap (on-screen Reference button),
verifies every bug condition, prevents regressions, and ships the change.

- [x] 1. Add the on-screen "Show Reference" control in the AR session
  - File: `main.html` around line 2261 (the session control row that holds
    the voice-guide toggle and the Diagnostics button).
  - Insert a new `<button>` as a sibling of the Diagnostics button, using the
    same pill styling (`background:#1F5A44; color:#F5F2EB; border-radius:9999px;
    padding:10px 18px; font-size:13px`) and an accent saffron dot
    (`background:#E0A23F`) so it reads as part of the same control group.
  - `onclick` handler: `app.showReferenceOverlay(app.currentPose, 5000)`.
  - Label: `Reference`; `title`: `Show the reference pose for 5 seconds`.
  - Guard: if `app.currentPose` is falsy when clicked, do nothing (the method
    already early-returns; no UI change needed).
  - _Fixes bug conditions 1.6 (on-screen control missing) and 2.6 (button
    parity with voice trigger)._

- [x] 2. Validate the inline `<script>` in `main.html` and `static/poses.js`
  parse as JavaScript
  - Extract the second `<script>` block from `main.html` to a temp file and
    run it through `new Function(...)` / `vm.Script` via Node.
  - Repeat for `static/poses.js` directly.
  - If either fails, fix the syntax error before proceeding; do not skip.
  - _Prevents regression 3.8 (both scripts must still parse)._

- [ ] 3. Smoke-test `/api/assistant` fallback path
  - Using Flask's `test_client`, POST to `/api/assistant` with a sample yoga
    prompt (for example `"How do I improve Tadasana?"`) while
    `OPENROUTER_API_KEY` and `GEMINI_API_KEY` are both unset.
  - Assert HTTP 200 and a non-empty `response` string in the JSON body.
  - Also confirm `/api/assistant` still enforces auth (401 when no session)
    before the authenticated smoke call.
  - _Verifies expected behaviors 2.1, 2.2 and preservation clauses 3.1, 3.2._

- [ ] 4. Manual trace of the voice `onresult` dispatch
  - Walk through `this.recognitionInstance.onresult` in `main.html` by
    reading the current handler and confirm that for every clause in
    requirement 2.3 (`stop`/`end`/`quit`, `score`/`accuracy`, `next`,
    `previous`, `reference`/`show pose`/`show image`, `repeat`/`again`,
    `voice guide on`/`voice guide off`) the matched branch returns or
    short-circuits before falling through to pose-name lookup.
  - Confirm the curated alias list in requirement 2.4 (`warrior one/two/
    three`, `down dog`, `side angle`, `half moon`, etc.) resolves to
    canonical `ASANA_LIBRARY` entries.
  - No code change expected; note any missing `return` and add it if found.
  - _Verifies expected behaviors 2.3, 2.4 and preservation clauses 3.3, 3.4._

- [ ] 5. Verify `showReferenceOverlay` idempotence
  - Inspect `showReferenceOverlay` in `main.html` and confirm it removes any
    existing `#reference-overlay` node before mounting a new one and before
    scheduling the auto-dismiss timeout, so rapid re-trigger cannot stack
    duplicates or leave a residual overlay after the first dismiss fires.
  - If the guard is not present, add `document.getElementById('reference-
    overlay')?.remove()` and `clearTimeout(this._refOverlayTimer)` at the
    top of the method, and store the new timeout id on
    `this._refOverlayTimer`.
  - _Fixes bug condition 1.7 and verifies expected behavior 2.7._

- [ ] 6. Clean up workspace-only helper scripts before committing
  - Remove the `_scripts/` directory (`_scripts/replace_gemini.py`,
    `_scripts/voice_upgrade.py`) — these were one-shot PowerShell-safe patch
    helpers and should not land in the repo. They are already gitignored,
    but remove the working-tree copy so the commit stays tidy.
  - Do not remove any other untracked files; only `_scripts/`.

- [ ] 7. Commit and push all three sub-fixes as one change
  - Stage `main.html`, `app.py`, and `.kiro/specs/ar-session-assistant-
    fixes/` (config, `bugfix.md`, `tasks.md`); leave `_scripts/` unstaged
    since it is gitignored and removed in task 6.
  - Commit message (single commit covering the three defects):
    ```
    Fix AR session assistant: proxy fallback, voice commands, reference overlay

    - Add /api/assistant Flask proxy with YOGA_FALLBACKS so the assistant
      always returns HTTP 200 even when no API key is set (fixes 2.1, 2.2)
    - Rewrite voice onresult to dispatch stop/score/next/previous/reference/
      repeat/voice-guide commands and a curated pose-alias list
      (fixes 2.3, 2.4)
    - Add showReferenceOverlay(poseName, durationMs) and an on-screen
      Reference button in the AR session, idempotent on rapid re-entry
      (fixes 2.5, 2.6, 2.7)
    ```
  - `git push origin main`. Render auto-deploys from `main`; the
    `git-credential-manager-core` warning on Windows is cosmetic — confirm
    `main -> main` appears in the push output.
  - After push, spot-check the live site at `https://asanaminds.onrender.com`:
    AR session loads, the Reference button is visible in the control row,
    clicking it mounts and dismisses the overlay within 5s.
