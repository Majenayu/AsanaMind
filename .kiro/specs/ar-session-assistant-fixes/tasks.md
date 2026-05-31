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

- [x] 4. Manual trace of the voice `onresult` dispatch
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

- [x] 5. Verify `showReferenceOverlay` idempotence
  - Inspect `showReferenceOverlay` in `main.html` and confirm it removes any
    existing `#reference-overlay` node before mounting a new one and before
    scheduling the auto-dismiss timeout, so rapid re-trigger cannot stack
    duplicates or leave a residual overlay after the first dismiss fires.
  - If the guard is not present, add `document.getElementById('reference-
    overlay')?.remove()` and `clearTimeout(this._refOverlayTimer)` at the
    top of the method, and store the new timeout id on
    `this._refOverlayTimer`.
  - _Fixes bug condition 1.7 and verifies expected behavior 2.7._

- [x] 6. Clean up workspace-only helper scripts before committing
  - Remove the `_scripts/` directory (`_scripts/replace_gemini.py`,
    `_scripts/voice_upgrade.py`) — these were one-shot PowerShell-safe patch
    helpers and should not land in the repo. They are already gitignored,
    but remove the working-tree copy so the commit stays tidy.
  - Do not remove any other untracked files; only `_scripts/`.

- [x] 7. Commit and push all three sub-fixes as one change
  - Stage `main.html`, `app.py`, and `.kiro/specs/ar-session-assistant-
    fixes/` (config, `bugfix.md`, `tasks.md`); leave `_scripts/` unstaged
    since it is gitignored and removed in task 6.
  - Commit message (single combined commit covering the AR session fixes
    plus the security hardening pass listed below):
    ```
    AR session fixes + security hardening pass
    ```
  - `git push origin VVCE-V1`. The branch tracks `origin/VVCE-V1`; the
    `git-credential-manager-core` warning on Windows is cosmetic — confirm
    `VVCE-V1 -> VVCE-V1` appears in the push output. Do **not** push to
    `main` and do **not** merge anything in this pass.
  - Verification (no live spot-check, no browser available): confirm
    `git log -1 --oneline origin/VVCE-V1` matches the local commit SHA.

## Security hardening (audit follow-up)

The 10-item audit summary identified items that were code-fixable. Each one
below is implemented and ships in the same `VVCE-V1` commit as the AR
session fixes.

- [x] 8. CSRF protection wired through the front-end
  - Server already exposes `GET /api/csrf` and a `@before_request` guard
    that rejects any state-changing `/api/*` POST/PUT/DELETE/PATCH without
    a matching `X-CSRF-Token` header (compared via `hmac.compare_digest`).
  - Carve-outs: `/login`, `/register`, `/auth/google`, `/api/health/report`
    (anonymous telemetry), `/api/live/upload`, `/api/live/stop` (camera
    frame push, gated by its own session check), `/api/assistant`
    (rate-limited, idempotent voice flow).
  - Front-end: `main.html`, `admin.html`, `org.html`, `profile.html`,
    `index.html` now install a global `fetch()` interceptor that auto-
    attaches `X-CSRF-Token` to every same-origin non-GET request and
    lazily fetches the token from `/api/csrf` if it isn't already on
    `window.__csrf_token`.

- [x] 9. NoSQL injection defense in `_parse_uploaded_excel`
  - Added the explicit `len(email) <= 254` check (RFC 5321 cap) on top of
    the existing type and regex defenses, so any oversized cell value
    fails fast before reaching a Mongo query.

- [x] 10. XSS sweep on `.innerHTML =` interpolations
  - Hoisted a single `esc()` helper at the top of `admin.html`, `org.html`,
    `main.html`, and `profile.html` and applied it to every dynamic value
    that flows into a template literal building HTML — student names,
    organization names, feedback text, certificate metadata, pose names
    in the profile chart, the master-cert verify URL, and the dashboard
    greeting.

- [x] 11. Admin login hardening
  - `app.py` already compares the submitted password using
    `hmac.compare_digest` (constant-time). The `rate_limit_admin_login`
    decorator caps `/admin/login` at `5 per 15 minutes` per IP — verified
    in the limiter setup; tightening was unnecessary.

- [x] 12. Rate limiter persistence
  - Verified the limiter prefers Mongo-backed storage when `MONGO_URI` is
    set and silently falls back to `memory://` only when the env var is
    absent or the `limits[mongodb]` extra is missing. Inline comment
    noting the design intent already lives in `app.py`.

- [x] 13. BlazePose vendoring
  - `static/pose-models.js` now probes `/static/vendor/mediapipe-pose/pose.js`
    first and falls back to JSDelivr at runtime if the local copy is
    absent. `solutionPath` follows the same base.
  - `scripts/fetch_offline_assets.py` extended to download the
    `pose.js`, wasm, and three `.tflite` landmark models into
    `static/vendor/mediapipe-pose/` for the operator to populate
    locally and commit when bandwidth permits.
  - The actual vendor bytes are NOT committed in this pass — the
    download is heavy from this environment; the runtime fallback path
    keeps the live site working off the CDN until the operator runs the
    fetch script and commits the vendor files.

- [x] 14. CI security audit
  - Added `.github/workflows/security-audit.yml` running `pip-audit -r
    requirements.txt --strict` on every push to `main`/`VVCE-V1`, every
    pull request, and weekly via cron.
