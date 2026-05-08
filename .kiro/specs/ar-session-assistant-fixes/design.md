# Bugfix Design Document

Paired with `bugfix.md`. Each section explains how the code will be brought
from the defect state in section 1 to the expected state in section 2 while
preserving everything in section 3.

## Defect Analysis

### Root Cause

Three defects share one underlying cause: the AR session surfaces the
assistant, voice control, and reference image as three independent features,
but none of them had a resilient failure path.

1. **AI assistant leaks "service not available"** — `callGeminiAssistant` in
   `main.html` called OpenRouter directly from the browser with a
   client-side key. When the key was rotated out of the bundle, or the
   upstream returned a 4xx/5xx, the browser surfaced the raw error because
   there was no server-side fallback to translate an outage into useful
   yoga guidance.

2. **Voice commands don't work** — `this.recognitionInstance.onresult` only
   ran a linear pose-name lookup against `ASANA_LIBRARY`. Control phrases
   (`stop`, `score`, `next`, `previous`, `reference`, `repeat`,
   `voice guide on/off`) and everyday English pose aliases
   (`warrior one`, `down dog`, `side angle`, `half moon`) never matched a
   canonical name and were silently dropped.

3. **Reference popup unreachable** — the user asked for a five-second
   full-screen reference photo during practice, triggerable by voice. The
   voice layer had no method to call; the practice UI had no button either,
   so non-voice users had no path to the overlay at all. The method, when
   added, could also stack duplicate DOM nodes on rapid re-entry because it
   tracked neither the existing overlay node nor the dismiss timer.

### Scope of Impact

- `app.py` — adds the resilient `/api/assistant` proxy. No impact on other
  routes.
- `main.html` — the in-session controls, the voice `onresult` handler, and
  a new full-screen overlay method. Bounded to the AR practice view; the
  dashboard, library, profile, and course views are untouched.
- `static/poses.js` — read-only from this spec; the voice `score` command
  reads `this._lastPoseScore`, which is already populated by
  `PoseEngine.evaluate`. No change.
- Deployment — the Render service auto-deploys from `main`; the live site
  absorbs the fix on the next push.

### Reproduction Path

1. _Assistant outage_ — load the app with `OPENROUTER_API_KEY` and
   `GEMINI_API_KEY` both unset, open the assistant, ask anything → the UI
   shows "service not available" (defect 1.1). Same result when the key is
   set but upstream returns a 5xx (defect 1.2).
2. _Voice controls_ — open AR practice with a pose selected, start voice,
   say `stop`, `score`, `next`, or `reference` → nothing happens (1.3).
   Say `warrior one` or `down dog` → nothing matches (1.4).
3. _Reference overlay_ — say `reference` → nothing appears (1.5). Look for a
   button in the session control row → none exists (1.6). Call
   `showReferenceOverlay` twice in under 250 ms → two `#reference-overlay`
   nodes mount and the first one lingers after the second auto-dismisses
   (1.7).

## Fix Strategy

### Approach

A single coherent change across three layers. The ordering is deliberate:
back-end first so the front-end has something reliable to call, front-end
logic second so the visible behaviors are wired up, and a minimal UI
addition last so the non-voice path exists too.

1. **Server-side proxy with curated fallback** — `/api/assistant` (Flask)
   reads `OPENROUTER_API_KEY` or `GEMINI_API_KEY` from the environment; on
   any failure mode (no key, upstream HTTP error, exception, timeout,
   empty choice) it returns `{success: true, source: 'fallback', text:
   <curated>}` chosen from `YOGA_FALLBACKS` by keyword. The client always
   sees HTTP 200 with a non-empty `text`. Authentication is preserved by
   gating on `session.get('logged_in')` so the route still 401s for
   unauthenticated callers, matching `/api/*` conventions elsewhere in
   `app.py`.

2. **Voice `onresult` dispatch table** — rewrite the handler so each
   recognised phrase hits exactly one action and `return`s before falling
   through. Order of precedence: meta commands (profile, logout, mic off)
   → in-session controls (reference, stop, score, next, previous, repeat,
   voice guide on/off) → pose-name match (curated alias map, then
   canonical English/Sanskrit). The alias map is a small object literal
   keyed by common English phrases (`warrior one`, `down dog`,
   `side angle`, `half moon`, `chair`, `bridge`, `child`, `triangle`,
   `dancer`, `bound angle`, `forward fold`, `upward salute`, etc.) that
   maps to canonical `ASANA_LIBRARY` names. A dispatched control phrase
   returns before pose matching, so `stop` cannot also be read as a pose
   lookup.

3. **Idempotent full-screen reference overlay** — `showReferenceOverlay
   (poseName, durationMs = 5000)` is a single method in the app object.
   On entry it (a) removes any existing `#reference-overlay` node, (b)
   clears the tracked dismiss timeout `this._refOverlayTimer`, then (c)
   mounts a fresh overlay, stores the new timeout id, and schedules the
   fade-out at `durationMs`. The DOM shape is fixed: a `<div
   id="reference-overlay">` covering the viewport, a centered pose photo
   (sourced from `asana.imagePath`, or the `PoseImage.dataUri` silhouette
   when no photo exists), a caption with the Sanskrit name and view, a
   close button top-right, click-outside-to-dismiss on the backdrop, and
   a 4 px countdown bar at the bottom that drains over the duration. No
   changes to `loadReferenceImage` or the side-panel reference image.

4. **On-screen Reference button** — adds a single button to the session
   control row in `main.html` at the existing cluster alongside the
   voice-guide toggle and the Diagnostics button. Same pill styling for
   visual parity: `background:#1F5A44; color:#F5F2EB; border-radius:
   9999px; padding:10px 18px; font-size:13px`, with a saffron
   (`#E0A23F`) dot matching the Diagnostics button. `onclick` calls
   `app.showReferenceOverlay(app.currentPose, 5000)`. The button renders
   only in the non-course AR view (inside the same `${!isCourseMode ?
   ... : ''}` branch as Diagnostics) so the course test screen stays
   uncluttered.

### Changes Required

- **File**: `app.py`
  - Add near the other imports: `import urllib.request, urllib.error,
    json` (json is likely already imported; no-op if so).
  - Add module-level `YOGA_FALLBACKS` dict and `yoga_fallback(prompt)`
    helper that keyword-matches from the dict and has a safe default.
  - Add `@app.route('/api/assistant', methods=['POST'])` route
    `assistant_proxy()` that 401s without session, 400s on empty prompt,
    otherwise returns 200 with either the AI response or a fallback.
    Upstream failures (`HTTPError`, generic `Exception`, empty choice)
    are caught and converted to fallbacks; the error is logged
    server-side via `print`.

- **File**: `main.html`
  - Rewrite `callGeminiAssistant(prompt)` to `fetch('/api/assistant', …)`
    with `credentials: 'same-origin'` and a network-error branch that
    still returns a short, calming message so `speakCorrection` never
    speaks "service unavailable".
  - Rewrite `this.recognitionInstance.onresult` with the dispatch table
    described above.
  - Add `showReferenceOverlay(poseName, durationMs)` as a method on the
    app object, immediately after `loadReferenceImage`.
  - Add the Reference button in the session control row beside the
    Diagnostics button (in the `renderARCorrection` template,
    inside the `!isCourseMode` branch). Wire its `onclick` to
    `app.showReferenceOverlay(app.currentPose, 5000)`.

- **File**: `static/poses.js`
  - No changes. The voice `score` command reads `this._lastPoseScore`
    which is set by `PoseEngine.evaluate` every frame.

### Side Effects

- **Server-side key introduction** — `/api/assistant` reads
  `OPENROUTER_API_KEY` or `GEMINI_API_KEY` from the environment. If
  neither is set on Render the proxy returns fallback text (by design).
  The user needs to set one of these in Render env vars to get live AI;
  this is explicit and documented in the commit message.
- **Client-side key removal** — the old in-page key is gone. Anyone who
  previously relied on `window.__gemini_api_key` from the template
  injection will need to use the proxy instead. Search of `main.html`
  shows `callGeminiAssistant` is the only consumer, so this is contained.
- **DOM node `#reference-overlay`** — introduced by the new method. It is
  appended to `document.body`, sits at `z-index:120` (above the AR video
  surface at `z-index:10` and the session controls at `z-index:20`), and
  is always cleaned up on dismiss.
- **Timer `this._refOverlayTimer`** — a new instance field on the app
  object; cleared on every re-entry.
- **Render deploy** — on push to `main`, Render rebuilds and redeploys.
  The service remains on the same URL.

## Verification

### Fix Checking

| Bug clause | Expected clause | Verification |
|---|---|---|
| 1.1 assistant says "service unavailable" with no key | 2.1 HTTP 200 + curated fallback when no key | `app.test_client().post('/api/assistant', json={'prompt':'How do I improve Tadasana?'})` with both env vars unset → status 200, body `{'success':True,'source':'fallback','text':<non-empty yoga string>}` |
| 1.2 upstream error propagates to UI | 2.2 upstream failures logged server-side, client sees fallback | Monkeypatch `urllib.request.urlopen` to raise `urllib.error.HTTPError`, POST same payload → status 200 + fallback text; stderr contains logged error |
| 1.3 control phrases ignored | 2.3 exactly-one-action dispatch | Read the rewritten `onresult` top-to-bottom and confirm each control branch ends in `return` before the pose-lookup section |
| 1.4 pose aliases ignored | 2.4 alias → canonical match | Inspect the alias map in `onresult`; spot-check `warrior one` → `Virabhadrasana I`, `down dog` → `Adho Mukha Svanasana`, `side angle` → `Utthita Parsvakonasana`, `half moon` → `Ardha Chandrasana` |
| 1.5 voice "reference" shows nothing | 2.5 overlay mounts and dismisses in `durationMs`±500ms | Manual: in the deployed app, say "reference" with a pose selected → overlay appears, countdown bar drains, overlay dismisses within ~5 s |
| 1.6 no on-screen control | 2.6 button parity with voice | DOM inspect `.renderARCorrection` output — the new button sits next to `Diagnostics` in the non-course branch, same pill styling; click produces identical overlay to the voice trigger |
| 1.7 duplicate overlays stack | 2.7 at most one `#reference-overlay` at any time | Manual: call `app.showReferenceOverlay('Tadasana', 5000)` twice within 100 ms in DevTools → `document.querySelectorAll('#reference-overlay').length === 1` |

### Preservation Checking

| Preservation clause | Verification |
|---|---|
| 3.1 AI path still works when key set | With `OPENROUTER_API_KEY` set, POST `/api/assistant` with prompt → status 200, `source: 'ai'`, non-empty text (deferred to deploy; local verification bounded to the fallback path) |
| 3.2 `/api/assistant` still requires auth | `test_client().post('/api/assistant', json={'prompt':'x'})` without logging in → status 401 |
| 3.3 exact Sanskrit names still match | Trace `onresult`: for transcript `tadasana`, the alias map misses, the canonical lookup matches `lib.find(a => ln === 'tadasana')` → `navigate('ar_correction'); selectAsanaAndStart('Tadasana')` |
| 3.4 voice toggle visuals unchanged | The `updateMicStatus` helper, `voice-listening`/`voice-talking` classes, and `mic-icon`/`voice-toggle`/`mic-status-text` elements are not touched |
| 3.5 side-panel reference image unchanged | `loadReferenceImage` is not modified; the overlay is a separate DOM node |
| 3.6 Diagnostics / voice-guide / end-session unchanged | Those buttons remain in place; the new Reference button is appended as a sibling, not swapped in |
| 3.7 per-frame `PoseEngine.evaluate` unchanged | No edit to `static/poses.js` or the `evaluatePose` call site |
| 3.8 both scripts still parse | Node-side parse check: extract the second inline `<script>` from `main.html` and the raw `static/poses.js`, run each through `new Function(src)` / `vm.Script(src)` → no thrown exception |

### Test Cases Required

Automated (included in this spec's execution):

1. **Fallback without key** — `/api/assistant` returns 200 + non-empty
   fallback text with `OPENROUTER_API_KEY` and `GEMINI_API_KEY` unset.
2. **Auth enforcement** — `/api/assistant` returns 401 for an
   unauthenticated session.
3. **Empty prompt** — `/api/assistant` returns 400 with `{'success':
   False, 'error': 'Empty prompt'}` for blank input.
4. **Script parse** — both `main.html` inline script and
   `static/poses.js` parse as valid JavaScript.

Manual (noted in `tasks.md` and verified on the deployed site):

1. Voice trigger for each control phrase and each alias.
2. Reference button click with and without a selected pose.
3. Rapid re-entry of `showReferenceOverlay` — one node only.
4. Live AI path — verify `source: 'ai'` in a browser network tab after
   the env var is set on Render.

### Regression Risks

- **Risk**: the new alias map could shadow a canonical Sanskrit name if
  an alias happens to be a substring of it. _Mitigation_: aliases are
  checked first via `transcript.includes(k)` in the alias map loop; the
  canonical lookup only runs when no alias matched. The alias set is
  curated English-only (`warrior one`, `down dog`, etc.) and does not
  overlap with any Sanskrit name in `ASANA_LIBRARY`.
- **Risk**: the full-screen overlay could trap user interaction if the
  dismiss timer fires while the tab is backgrounded and `setTimeout` is
  throttled. _Mitigation_: the backdrop has a click-outside dismiss
  handler and the explicit close button, so dismissal never depends
  solely on the timer.
- **Risk**: the proxy log output could leak user prompts to Render
  logs. _Mitigation_: only upstream error codes and messages are
  `print`ed; the prompt itself is not logged.
- **Risk**: the `urllib.request` import could fail on minimal Python
  builds. _Mitigation_: it is part of the standard library; no new
  `requirements.txt` entry is needed.
- **Risk**: syntax regressions in `main.html` during the voice rewrite
  would black-screen the AR view. _Mitigation_: task 2 in `tasks.md`
  runs a Node-side parse check on the inline script before commit.
