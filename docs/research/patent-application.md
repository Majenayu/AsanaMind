---
title: "PATENT APPLICATION — Form 2: Specification"
applicant_name: "P. G. Ayush Rai"
applicant_address: "[Full residential address]"
applicant_nationality: "Indian"
inventor_name: "P. G. Ayush Rai"
inventor_address: "[Full residential address]"
date: "2026"
jurisdiction: "Indian Patent Office (CGPDTM), New Delhi"
classification:
  ipc: "G06V 40/20 — Recognition of human body motions"
  ipc_secondary: "G06N 3/045 — Combinations of multiple neural networks"
  ipc_tertiary: "A63B 71/06 — Indicating or scoring devices for sport"
---

> **NOTICE**
>
> This document is a *drafting template* for a complete specification
> filed at the Indian Patent Office. It is structured per the Patents
> Act, 1970, the Patents Rules, 2003, and the Form 2 (Complete
> Specification) layout. **It is not legal advice.** Before filing,
> engage a registered patent agent (a list is at
> <https://ipindia.gov.in>) to:
>
> 1. Conduct a *prior-art search* against existing patents
>    (especially KR/JP/CN filings on AI yoga from 2018–2024).
> 2. Prepare and notarise drawings (Figures 1–4 are referenced but
>    must be drafted as line drawings on A4 sheets).
> 3. File via the e-filing portal (<https://ipindiaonline.gov.in>)
>    along with Form 1 (Application), Form 5 (Declaration of
>    Inventorship), and government fee (₹1,600 for an individual /
>    Startup vs ₹8,000 for a company).
> 4. Decide whether to file a *Provisional* (12 months grace, ~70%
>    cheaper) before this Complete Specification.

---

# FORM 2 — THE PATENTS ACT, 1970 — Complete Specification

## TITLE OF THE INVENTION

A BROWSER-NATIVE PRIVACY-PRESERVING SYSTEM AND METHOD FOR
HYSTERESIS-FILTERED REAL-TIME YOGA POSE COACHING WITH
PRIORITY-RESOLVED VOICE COMMAND GRAMMAR

## (a) FIELD OF THE INVENTION

The present invention relates to the field of computer-assisted
physical instruction, more particularly to systems and methods for
real-time pose-correction feedback during yoga practice using on-device
machine learning inference and voice-driven hands-free interaction. The
invention further relates to multi-tenant architecture for deploying
such systems at institutional scale.

## (b) BACKGROUND OF THE INVENTION

Existing AI-assisted yoga systems suffer from at least the following
deficiencies:

(i) **Native-app distribution dependence.** Conventional yoga apps
require installation through Apple App Store, Google Play Store, or
proprietary device sideloading, creating administrative overhead for
institutional rollout (educational institutions, corporate wellness
programmes) and excluding low-end devices that lack the storage to
host such applications.

(ii) **Cloud-side pose inference.** Existing systems that perform
pose estimation on a remote server transmit raw video frames or
extracted skeletal data over the network. This (a) introduces latency
that defeats real-time coaching, (b) requires reliable broadband
connectivity inappropriate for users in low-connectivity regions, and
(c) creates a privacy liability — biometric data is regulated under
the Digital Personal Data Protection Act, 2023.

(iii) **Frame-level feedback chatter.** Conventional rule-based pose
scoring emits an audio correction whenever a rule fails on the current
frame and rescinds it whenever the rule passes, producing oscillating
spoken feedback (e.g., "lift your knee" and "knee corrected" repeating
several times per second) that is cognitively burdensome and
counter-productive to practice.

(iv) **Voice-command ambiguity.** Existing voice-controlled fitness
applications cannot distinguish between *action commands* (e.g.,
"next pose", "what is my score?") and *content references* (e.g.,
"warrior two" — referring to the pose Virabhadrasana II). When the
spoken token "two" is parsed as a numeral, the action grammar fails,
and when the action grammar takes priority, the user cannot verbally
select certain poses.

(v) **Lack of institutional partition.** Existing systems are designed
for individual consumers; they do not support a tenant-isolated data
model in which a college can onboard 1,000 students with strict
guarantees that no other tenant's data is accessible.

There exists, therefore, a need for a yoga coaching system that
(a) runs natively in a browser without app installation, (b) executes
pose inference on-device for privacy and latency, (c) suppresses
frame-level feedback chatter through stateful filtering, (d)
disambiguates voice commands deterministically, and (e) supports
multi-tenant institutional deployment.

The present invention addresses each of the above deficiencies.

## (c) OBJECTS OF THE INVENTION

The principal objects of the present invention are:

1. To provide a yoga coaching system that operates in any modern web
   browser without requiring native application installation.

2. To provide such a system in which all biometric inference (pose
   estimation, alignment scoring) is performed on the user's local
   computing device and no raw video, image, or skeletal keypoint
   data is transmitted to any remote server.

3. To provide a method of converting per-frame pose rule evaluations
   into spoken corrections through a per-rule fail/pass debounce
   filter (hereinafter "hysteresis filter") that suppresses transient
   detection artefacts and emits feedback only after a sustained
   condition is observed.

4. To provide a voice-command interpretation method that resolves
   ambiguity between action commands and content references through
   priority-ordered regular expression matching with a fallback fuzzy
   pose-name lookup.

5. To provide a multi-tenant institutional deployment model in which
   data is partitioned by organisational email domain with route-level
   access enforcement.

6. To provide a six-semester certificate programme integrating
   real-time pose evaluation with quiz-based knowledge assessment,
   issuing cryptographically-signed completion certificates.

## (d) SUMMARY OF THE INVENTION

The present invention discloses a system and method for real-time
yoga pose coaching, comprising:

(i) a *client device* (a personal computer, laptop, tablet, or
mobile phone) executing a web browser supporting the WebGL and
WebSpeech APIs;

(ii) a *pose estimation module* loaded via the said web browser,
comprising a convolutional neural network for single-person pose
estimation (in the preferred embodiment, MoveNet SinglePose
Thunder) executing within a JavaScript runtime environment using
WebGL hardware acceleration;

(iii) a *rule engine* comprising a finite, per-pose set of
predicates over the smoothed keypoints, where each predicate is
either an angle constraint between three keypoints or a distance-
ratio constraint between two pairs of keypoints, and is associated
with a natural-language correction string;

(iv) a *hysteresis filter* comprising, for each predicate, a fail
counter and a pass counter, and a state flag taking values in the
set {silent, speaking}, wherein:
  (a) a correction is emitted to a speech synthesis subsystem only
      when the fail counter for the corresponding rule equals or
      exceeds a fail threshold (default seven frames);
  (b) the state flag transitions from speaking back to silent only
      when the pass counter equals or exceeds a pass threshold
      (default five frames);

(v) a *voice command grammar* comprising a priority-ordered list of
regular expressions, each mapped to a fixed action handler, with a
fallback fuzzy lookup against a catalogue of pose names;

(vi) a *server-side multi-tenant data layer* in which records are
partitioned by an organisational email domain identifier, and
read/write operations are gated by a request-level access decorator
that injects the requesting user's organisational identifier into
the database query;

(vii) a *certification module* that records per-pose alignment
sessions and quiz outcomes, computes per-semester completion, and
issues cryptographically signed PDF certificates.

The said hysteresis filter is the technical heart of the
invention; the priority-resolved voice grammar is the second core
contribution; the multi-tenant model is the third.

## (e) BRIEF DESCRIPTION OF THE DRAWINGS

The accompanying drawings (to be prepared as A4 line drawings)
illustrate:

- **Figure 1.** System architecture: client device ↔ web server ↔
  multi-tenant database, with the on-device pose-estimation
  pipeline highlighted as residing entirely client-side.

- **Figure 2.** Hysteresis filter state diagram: states {silent,
  speaking} with transitions labelled (fail≥F → speak), (pass≥P →
  silent).

- **Figure 3.** Priority-ordered voice command resolution flow:
  utterance → action regex matching → fallback pose lookup → action
  dispatch.

- **Figure 4.** Multi-tenant data isolation: per-request access
  decorator injecting `organizationEmail` into all collection
  queries.

## (f) DETAILED DESCRIPTION OF THE INVENTION

### 1. The Client-Side Pose Pipeline

[Detailed description of the per-frame pipeline as in Section
III.B of the research paper. Refer to Figure 1.]

### 2. The Rule Grammar (Claim 1 / Claim 6 basis)

A pose `P` is characterised by:

```
P = (N, S, R, T)
    N — Sanskrit name
    S — stance class ∈ {stand, seat, prone, supine}
    R — finite rule set {r_1, ..., r_k}
    T — target hold duration (seconds)

r_i = (φ_i, τ_i, c_i)
    φ_i — predicate over smoothed keypoints
    τ_i — confidence threshold
    c_i — natural-language correction string

φ ::= angle(K_a, K_b, K_c) ∈ [θ_min, θ_max]
    | dist(K_a, K_b) / dist(K_c, K_d) ∈ [ρ_min, ρ_max]
```

Twenty curated poses are encoded in this grammar; the complete
rule sets are in Annexure A.

### 3. The Hysteresis Filter (Independent Claim 1)

The state machine for each rule i:

```
state[i]      ∈ {silent, speaking}    initially silent
fail_cnt[i]   ∈ ℕ                     initially 0
pass_cnt[i]   ∈ ℕ                     initially 0
F             = 7   (fail threshold)
P             = 5   (pass threshold)
```

On each frame at time t:

```
if NOT φ_i(p̂_t):                      // rule failing
    fail_cnt[i] := fail_cnt[i] + 1
    pass_cnt[i] := 0
    if state[i] = silent and fail_cnt[i] ≥ F:
        emit_speech(c_i)
        state[i] := speaking
else:                                  // rule passing
    pass_cnt[i] := pass_cnt[i] + 1
    fail_cnt[i] := 0
    if state[i] = speaking and pass_cnt[i] ≥ P:
        state[i] := silent
```

The asymmetry F > P is intentional: the system enters the speaking
state cautiously (requires 280 ms of failure at 25 fps) but exits it
quickly (requires 200 ms of passing) — rewarding the user's
correction with rapid silence.

### 4. The Voice Command Grammar (Independent Claim 2)

```
RESOLVE(utterance):
    for each (regex_j, handler_j) in PRIORITY_TABLE:
        if regex_j.test(utterance):
            return handler_j(utterance)
    pose_name := fuzzy_match(utterance, ASANA_LIBRARY)
    if pose_name is not null:
        return select_pose(pose_name)
    return error_unrecognised
```

Where PRIORITY_TABLE is a static ordered list of 12 (regex,
handler) pairs covering: end session, score query, next/previous,
reference overlay, repeat, voice toggle, breath toggle, diagnostics,
hold timer, and pose modifications. The fallback fuzzy match uses
a normalised Levenshtein distance against the canonical Sanskrit
and English aliases of the 20 poses in the library.

### 5. The Multi-Tenant Data Layer (Independent Claim 3)

Each request to a protected route passes through a decorator that:

```
def require_org(handler):
    def wrapper(request):
        user = authenticate(request)
        if user.role not in {"org_admin", "student"}: deny()
        request._org_email := user.organizationEmail
        return handler(request)
    return wrapper
```

All MongoDB queries within `handler` then filter by
`{ organizationEmail: request._org_email }`. There is no code path
in the application by which an org_admin can query data outside
their `organizationEmail` scope.

### 6. The Certification Module (Independent Claim 4)

A pose `P` is *passed* by user `u` when:

```
∃ session s: 
    s.user = u, s.pose = P, max_duration_at(score ≥ 90%, s) ≥ T_P

AND

∃ quiz_attempt q:
    q.user = u, q.pose = P, q.score = 100%
```

A semester is *passed* when all its poses are passed. The master
certificate is *issued* when all six semesters are passed; the
certificate is a PDF signed with an RSA-2048 key whose public half
is published at a verification URL embedded in the PDF.

## (g) CLAIMS

We claim:

**1.** A method for real-time yoga pose coaching, comprising:

  (a) capturing a video stream from a user-facing camera of a
      client device;

  (b) executing a single-person convolutional pose-estimation
      neural network within a web browser running on the said
      client device, said neural network producing a set of
      keypoint coordinates and confidence scores per frame;

  (c) smoothing said keypoint coordinates by an exponential moving
      average to obtain smoothed keypoints;

  (d) evaluating, against the said smoothed keypoints, a finite set
      of pose-specific rule predicates each comprising either an
      angle constraint over three keypoints or a distance-ratio
      constraint over two pairs of keypoints;

  (e) maintaining, for each said rule predicate, a fail counter and
      a pass counter, and a state flag taking values in {silent,
      speaking};

  (f) emitting a corresponding pre-defined natural-language
      correction string to a speech synthesis subsystem if and only
      if the said state flag for the said rule predicate is silent
      AND the said fail counter exceeds a fail threshold;

  (g) transitioning the said state flag from speaking back to silent
      if and only if the said pass counter exceeds a pass threshold;

  characterised in that the said fail threshold is strictly greater
  than the said pass threshold, and the said keypoint inference of
  step (b) is performed entirely on the said client device with no
  raw video, image, or keypoint data transmitted to any remote
  server.

**2.** A method for resolving voice commands during yoga practice,
comprising:

  (a) receiving a recognised speech utterance from a speech-
      recognition subsystem of a web browser;

  (b) testing the said utterance against a priority-ordered list of
      regular expressions each mapped to a respective action
      handler;

  (c) invoking the action handler corresponding to the first said
      regular expression that matches the said utterance;

  (d) and only if no said regular expression matches, performing a
      fuzzy lexical match of the said utterance against a catalogue
      of pose names and invoking a pose-selection action;

  characterised in that the said priority-ordered list disambiguates
  utterances containing tokens that are simultaneously valid as
  action keywords and as pose-name components by deterministically
  resolving in favour of the action.

**3.** A multi-tenant deployment system for the method of claim 1,
comprising:

  (a) a server-side data store partitioned by an organisational
      email-domain identifier;

  (b) an authentication subsystem that associates each authenticated
      user with exactly one said organisational identifier;

  (c) an access-control decorator applied to each protected route
      handler that injects the said organisational identifier into
      database query filters,

  characterised in that no application code path permits a request
  authenticated under one said organisational identifier to read or
  modify data associated with a different said organisational
  identifier.

**4.** A certification method for use with the method of claim 1,
comprising:

  (a) recording, for each pose-practice session, the maximum
      duration during which the said alignment score (computed as
      the fraction of said rule predicates passing) remained at or
      above ninety percent;

  (b) recording, for each said pose, the score on a fixed-question
      anatomical quiz;

  (c) marking the said pose as passed when the said maximum duration
      at or above ninety percent is at least ten seconds AND the
      said quiz score is one hundred percent;

  (d) marking a semester as passed when all poses assigned to the
      said semester are marked passed;

  (e) issuing a cryptographically signed PDF certificate when all
      six semesters of a fixed curriculum are marked passed.

**5.** The method of claim 1 wherein the said exponential moving
average smoothing parameter is in the range [0.5, 0.7] and the
said pose-estimation neural network is MoveNet SinglePose Thunder.

**6.** The method of claim 1 wherein the said fail threshold is
seven frames and the said pass threshold is five frames at a
nominal frame rate of twenty-five frames per second.

**7.** The method of claim 1 wherein the said rule predicates for
asymmetric poses are parameterised by a leading-side flag and the
said voice command grammar of claim 2 accepts said leading-side as
an optional suffix to the said pose name.

**8.** The system of claim 3 further comprising a bulk-onboarding
subsystem that ingests an Excel spreadsheet of student records,
validates each record against the said organisational domain,
generates a single-use invitation token per record, and dispatches
a magic-link email containing the said token.

**9.** A non-transitory computer-readable medium storing
instructions which, when executed by one or more processors of a
client device having a camera and a microphone, cause the said
processors to perform the method of claim 1.

**10.** A system comprising one or more client devices and a
server, configured to perform the method of claim 1 in combination
with the multi-tenant deployment system of claim 3 and the
certification method of claim 4.

## (h) ABSTRACT OF THE DISCLOSURE

Disclosed is a browser-native system and method for real-time yoga
pose coaching. A web-based client device captures camera video,
executes an on-device convolutional pose-estimation neural network,
and evaluates the detected keypoints against per-pose rule predicates.
A novel hysteresis filter — a per-rule fail/pass debounce state
machine with asymmetric thresholds (fail strictly greater than pass)
— suppresses frame-level feedback chatter and emits spoken corrections
only after a sustained failure is observed, returning to silence only
after a sustained recovery. A priority-ordered voice command grammar
deterministically disambiguates action commands from content
references. A server-side multi-tenant data layer partitions student
records by organisational email domain with route-level access
enforcement. A certification module integrates pose practice and quiz
performance to issue cryptographically signed completion certificates
for a fixed six-semester twenty-pose curriculum. No raw video, image,
or keypoint data is transmitted from the client device.

---

# ANNEXURES (to be appended)

- **Annexure A.** Complete rule sets for the twenty curated asanas
  (formatted as a table; rows include pose name, stance class,
  rule predicate, threshold range, correction string).

- **Annexure B.** Example regex priority table for the voice
  command grammar.

- **Annexure C.** Example bulk-onboarding Excel template format.

- **Annexure D.** Sample certificate PDF showing the embedded
  verification URL and the RSA signature block.

---
*This specification is filed in respect of an invention; the
applicant requests that a patent may be granted to him for the
invention described and claimed herein.*

**Date.** [DD/MM/2026]

**Signature of applicant.** _______________________________

**Name.** P. G. Ayush Rai
