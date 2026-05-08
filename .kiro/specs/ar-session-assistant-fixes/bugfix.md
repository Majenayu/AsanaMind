# Bugfix Requirements Document

## Introduction

Three interrelated defects in the AR practice session of the AsanaMind Flask app
(`main.html`, served from `/home`) are degrading the core in-session experience:

1. The AI assistant surfaces a generic "service not available" error to the user
   whenever the upstream Gemini/OpenRouter call cannot be completed — most
   commonly because the API key has been rotated or was never set on the
   deployment. The assistant is meant to be a calm, always-available coach, so
   any hard failure breaks the session feel.
2. The speech-recognition `onresult` handler only matches exact pose names, so
   practical session controls — `stop`, `score`, `next`, `previous`,
   `reference`, `repeat`, `voice guide on/off` — and everyday English pose
   aliases ("warrior one", "down dog", "side angle", "half moon", etc.) are
   ignored or silently misrouted.
3. The user-requested full-screen reference overlay (a 5-second photo of the
   ideal pose, triggerable during practice) does not exist end-to-end. The
   voice trigger has nothing to call, and there is no on-screen control for
   users who do not use voice, so non-voice users have no way to summon the
   overlay at all.

This spec defines the fix for all three defects as a single coherent change,
using the bug-condition methodology so each defect is checked independently
(fix checking) and existing working behavior is preserved (preservation
checking).

## Bug Analysis

### Current Behavior (Defect)

The following clauses describe behavior the fixed code must no longer exhibit.

1.1 WHEN a user asks the AI assistant a question AND neither
`OPENROUTER_API_KEY` nor `GEMINI_API_KEY` is set on the server THEN the system
surfaces a generic "service not available" / network error to the user instead
of any useful yoga response.

1.2 WHEN the upstream AI provider returns a non-2xx response or the request
times out THEN the error is propagated to the browser and the user sees a
failure state instead of a graceful fallback.

1.3 WHEN the user speaks an AR-session control phrase — `stop` / `end` /
`quit`, `score` / `accuracy`, `next`, `previous`, `reference` / `show pose` /
`show image`, `repeat` / `again`, `voice guide on` / `voice guide off` — the
`onresult` handler takes no action or misinterprets the phrase as a pose-name
lookup that fails.

1.4 WHEN the user speaks a common English pose alias (`warrior one`,
`warrior two`, `warrior three`, `down dog`, `side angle`, `half moon`, and the
other curated aliases) THEN the system fails to match any pose and takes no
action.

1.5 WHEN the user says `reference`, `show pose`, or `show image` during AR
practice THEN no full-screen reference overlay is shown.

1.6 WHEN a user is in AR practice AND is not using voice THEN there is no
on-screen control to summon the reference-image overlay, so the overlay is
unreachable for that user.

1.7 WHEN `showReferenceOverlay` is triggered twice in rapid succession THEN
duplicate `#reference-overlay` nodes can stack in the DOM, leaving a residual
overlay after the first one dismisses.

### Expected Behavior (Correct)

The following clauses describe behavior the fixed code must exhibit for the
same conditions listed above.

2.1 WHEN a user asks the AI assistant a question AND neither
`OPENROUTER_API_KEY` nor `GEMINI_API_KEY` is set on the server THEN the system
SHALL respond with HTTP 200 and a non-empty yoga-oriented fallback response
drawn from the curated fallback set, never surfacing a service-unavailable
error to the UI.

2.2 WHEN the upstream AI provider returns a non-2xx response or the request
times out THEN the system SHALL log the upstream failure server-side and
respond to the client with HTTP 200 and a non-empty fallback response, so the
user always hears a useful reply.

2.3 WHEN the user speaks an AR-session control phrase (`stop` / `end` /
`quit`, `score` / `accuracy`, `next`, `previous`, `reference` / `show pose` /
`show image`, `repeat` / `again`, `voice guide on` / `voice guide off`) THEN
the `onresult` handler SHALL invoke exactly one matching action — end session,
speak the current alignment score, cycle to the next or previous library pose,
mount the reference overlay, replay the last spoken cue, or toggle the voice
guide — without also triggering a pose-name lookup or any other action.

2.4 WHEN the user speaks a curated English pose alias (`warrior one` /
`warrior two` / `warrior three`, `down dog`, `side angle`, `half moon`, and the
rest of the curated alias list) THEN the system SHALL switch the current pose
to the corresponding canonical entry in `ASANA_LIBRARY`.

2.5 WHEN the user says `reference`, `show pose`, or `show image` during AR
practice AND a `currentPose` is set THEN the system SHALL call
`showReferenceOverlay(currentPose, 5000)`, which SHALL mount exactly one
`#reference-overlay` element and auto-dismiss it within `durationMs` ± 500 ms
with a visible countdown progress bar.

2.6 WHEN a user is in AR practice AND is not using voice THEN the system SHALL
expose an on-screen "Show Reference" control rendered alongside the existing
session controls (same pill styling as the Diagnostics button) that, when
pressed, invokes `showReferenceOverlay(currentPose, 5000)` and produces an
overlay with the same DOM, same duration, and same dismiss behavior as the
voice-triggered overlay.

2.7 WHEN `showReferenceOverlay` is called while an overlay is already mounted
THEN the system SHALL remove the existing `#reference-overlay` before mounting
the new one, so at most one `#reference-overlay` node exists at any time.

### Unchanged Behavior (Regression Prevention)

The following clauses describe currently-working behavior the fix must
preserve.

3.1 WHEN `OPENROUTER_API_KEY` or `GEMINI_API_KEY` IS set AND the upstream
provider returns a successful response THEN the system SHALL CONTINUE TO
return that AI-generated response to the client with the same text content it
produces today.

3.2 WHEN a user is signed in and hits `/api/assistant` with a valid prompt
THEN the system SHALL CONTINUE TO require authentication (401 for
unauthenticated callers) as it does for other `/api/*` routes.

3.3 WHEN the user speaks an exact canonical Sanskrit pose name (for example,
`Tadasana`, `Vrikshasana`, `Adho Mukha Svanasana`) THEN the system SHALL
CONTINUE TO switch to that pose.

3.4 WHEN the user presses the voice-assistant button in the top bar THEN the
system SHALL CONTINUE TO start and stop `SpeechRecognition` with the same
listening / talking visual states it shows today.

3.5 WHEN a user opens AR practice with a selected pose THEN the system SHALL
CONTINUE TO load the side-panel reference image through
`loadReferenceImage(poseName)` and display it in `#reference-image` as it does
today.

3.6 WHEN a user presses the existing Diagnostics toggle, the voice-guide
toggle, or the end-session control THEN the system SHALL CONTINUE TO behave
identically to the pre-fix implementation.

3.7 WHEN pose evaluation runs each frame THEN the system SHALL CONTINUE TO
call `PoseEngine.evaluate`, update the on-screen score, and render skeleton
overlays with no change in timing, accuracy, or frame rate.

3.8 WHEN `main.html` or `static/poses.js` is loaded THEN the system SHALL
CONTINUE TO parse as valid JavaScript — the fix must not introduce syntax
errors in either script.
