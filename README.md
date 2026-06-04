<div align="center">

# AsanMinds — Sunday

**An AI-powered AR yoga instructor in your browser.**
Real-time pose correction · Voice coach · 6-semester course · Verified certificates

[![Live](https://img.shields.io/badge/live-asanaminds.onrender.com-0F3D2E?style=flat-square)](https://asanaminds.onrender.com)
![PWA](https://img.shields.io/badge/PWA-installable-C2552F?style=flat-square)
![Privacy](https://img.shields.io/badge/pose_detection-on--device-3E8A52?style=flat-square)

</div>

---

## What it is

AsanMinds is a yoga learning platform built around three things students typically miss:

1. **A teacher who watches** — a browser-based AI coach using TensorFlow.js MoveNet that scores your pose 30 times a second and tells you exactly what to fix.
2. **Structure that fits a busy life** — six six-month semesters that step you from beginner asanas to advanced standing balances, designed for engineering students with exams and labs in the way.
3. **Credentials worth keeping** — every passed semester earns a verified PDF certificate with a public verification URL and QR code, so your work is provable.

Everything runs in the browser. The camera feed never leaves your device for the AR detection — only the score and your progress get saved.

## Highlights

| | |
|---|---|
| 🧘 **20-pose library** | Beginner to advanced asanas with rich notes — Sanskrit meaning, alignment cues, breath, common mistakes, modifications, contraindications |
| 🎯 **AR pose correction** | MoveNet skeleton overlay, per-joint scoring, mirror-aware cues, asymmetric pose left/right tracking |
| 🎤 **Voice coach "Sunday"** | Wake-word activation, 40+ commands, offline pose knowledge base + AI fallback, voice-controlled course flow |
| 🎓 **6-semester course** | 3rd → 8th sem, monthly progress windows, pose unlock chain, AR + theory quiz tests, master certificate |
| 📜 **Verified certificates** | A4 landscape PDF, server-issued, QR code → public `/verify/<id>` URL, per-pose marks, optional email delivery |
| 📱 **Mobile-first PWA** | Portrait AR view, install to home screen, offline-capable, push notifications |
| 🔥 **Streaks + freezes** | Daily practice tracking, one freeze per week so a missed day doesn't break months of work |
| 🛡️ **Adaptive difficulty** | Tolerance softens after 3 sub-70% sessions; lighting/framing pre-check before each test |
| 👤 **Google sign-in** | One-tap auth with verified emails — certificates land in inboxes that actually exist |
| 🎛️ **Admin panel** | Dashboard, student deep-dives, edit/delete, broadcast push, feedback aggregation, CSV export, live coach view |

## Live demo

🌐 **https://asanaminds.onrender.com**

Sign in with Google to start. Once registered, the dashboard, library, practice, course, and profile views all become available.

## Tech stack

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│   ├─ TensorFlow.js + MoveNet (on-device pose detection)      │
│   ├─ Web Speech API (voice coach)                            │
│   ├─ jsPDF + QRious (certificate generation)                 │
│   └─ Service Worker (offline + push)                         │
├──────────────────────────────────────────────────────────────┤
│  Flask (Python 3.10+)                                        │
│   ├─ Google ID-token verification (google-auth)              │
│   ├─ flask-limiter (30/min on AI endpoint)                   │
│   ├─ SendGrid (certificate emails)                           │
│   └─ pywebpush (daily reminders)                             │
├──────────────────────────────────────────────────────────────┤
│  MongoDB Atlas                                               │
│   ├─ google_auth.* — Google-signed-in users                  │
│   ├─ face_auth.* — legacy email users (disabled by default)  │
│   └─ admin_data.* — feedback, audit log, live frames (TTL)   │
├──────────────────────────────────────────────────────────────┤
│  Render (web service)                                        │
│   └─ gunicorn 1 worker × 4 threads                           │
└──────────────────────────────────────────────────────────────┘
```

## Project layout

```
.
├── app.py                  # Flask routes + auth + admin panel + APIs
├── index.html              # Login page (Google sign-in)
├── main.html               # Single-page student app
├── profile.html            # User profile + activity heatmap + certs strip
├── admin.html              # Single-page admin SPA
├── sw.js                   # Service worker (cache + push)
├── manifest.json           # PWA manifest
├── Procfile                # Render gunicorn config
├── requirements.txt        # Python deps
├── runtime.txt             # Pinned Python version
├── static/
│   ├── poses.js            # 20-pose library + rule engine + scoring
│   ├── pose-notes.js       # Rich pedagogical notes per pose
│   ├── pose-cues.js        # Voice cue scripts per asana
│   ├── practice-flow.js    # Session recap, breath pacing, drift detection
│   ├── courses.js          # 6-semester course definitions + utils
│   └── voice-kb.js         # Offline knowledge base for the voice coach
└── assets/
    ├── logo.png
    └── poses/              # Reference photos for all 20 asanas
```

## Local setup

```bash
git clone https://github.com/Majenayu/AsanaMind.git
cd AsanaMind
pip install -r requirements.txt
```

Create a `.env` file (or export the variables) — at minimum:

```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
MONGO_URI=mongodb+srv://...        # your Atlas cluster
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
```

Optional but recommended:
```bash
ADMIN_EMAILS=you@gmail.com         # comma-separated
ADMIN_PASSWORD=...                 # second factor on top of the email
LIVE_VIEW_PASSWORD=...             # for the admin live coach view
SENDGRID_API_KEY=SG....             # for emailing certificates
SENDGRID_FROM_EMAIL=verified@...
VAPID_PUBLIC_KEY=...                # for daily push reminders (use py-vapid to generate)
VAPID_PRIVATE_KEY=...
OPENROUTER_API_KEY=sk-or-...        # for the AI fallback in the voice coach
```

Then:
```bash
python app.py        # dev server on :5000
```

## Deploy to Render

The repo ships ready-to-deploy. After connecting it to a Render web service:

1. **Build command**: `pip install -r requirements.txt`
2. **Start command**: defined in `Procfile` (gunicorn, single worker, 4 threads)
3. **Environment**: paste in every variable from the `.env` block above
4. **Auto-deploy**: every push to `main` triggers a redeploy

The app refuses to start in production if `SECRET_KEY` or `MONGO_URI` is missing — this is intentional, no insecure defaults.

For institution-specific deployments, see [`docs/organization-admin-and-scaling.md`](docs/organization-admin-and-scaling.md) for sub-admin batch setup, multi-instance vs. shared SaaS architecture, and per-client environment variable guidance.

## How the course works

| Sem | Asanas | Theme |
|---|---|---|
| 3 | Tadasana, Urdhva Hastasana, Anjali Mudra, Vrikshasana | Foundations — standing alignment |
| 4 | Uttanasana, Sukhasana, Dandasana | Grounding — folding and seating |
| 5 | Baddha Konasana, Paschimottanasana, Balasana | Restoration — opening hips, calming |
| 6 | Adho Mukha Svanasana, Virabhadrasana I, Virabhadrasana II | Strength — first true vinyasa |
| 7 | Trikonasana, Utkatasana, Parsvakonasana, Setu Bandhasana | Lateral body + chair work |
| 8 | Virabhadrasana III, Ardha Chandrasana, Natarajasana | Mastery — advanced balance |

Each pose requires both an **AR alignment test** (best of 3 attempts, ≥90% held for 10s — or after 3 attempts the best score auto-passes) and a **theory quiz** (3 questions drawn from the pose notes, ≥2/3 to pass). Pose mark = mean of the two; course mark = mean of pose marks; master mark = mean of course marks.

Sem N+1 unlocks only when Sem N is fully completed AND the date opens. Course windows are 6 months wide, anchored to the user's registration date.

## How the AR scoring works

`static/poses.js` implements **template matching** — for each pose, a reference vector of joint angles (extracted from biomechanics literature and the reference photos in `assets/poses/`). Each frame, the live joint angles are compared element-wise against both the original reference and the left-right mirrored reference; the closer match wins. Score = `100 × (1 − avg_error / 1.2)`, where error is the joint deviation in tolerance units.

The top-3 worst joints become the displayed corrections, with mirror-safe wording so users in a flipped video feed don't get confused. EMA smoothing on keypoints, hysteresis on rule transitions, and confidence suppression on low-quality detections keep cues from flickering.

For asymmetric poses (Warrior I/II/III, Triangle, Half Moon, Dancer) the engine detects which leg is forward and reports per-side scores: *"Stronger on the right (+12 pts)"*.

## Privacy

- **Pose detection runs on-device.** Camera frames go through TensorFlow.js in the browser and never leave it for the scoring pipeline.
- **Server stores**: progress, certificate metadata, feedback, push subscriptions. Not video.
- **Sessions** are HttpOnly + Secure + SameSite=Lax + 30-day expiry, signed with a secret that's not in the source.
- **Account deletion** wipes the user document plus every related collection in both DBs (see `/api/delete-account`).
- **Public verify URL** (`/verify/<cert_id>`) shows only what's already on the certificate — name, course, mark, issue date.

Full privacy policy is shipped at [/privacy](https://asanaminds.onrender.com/privacy).

## API surface

A condensed list — see `app.py` for the full set with auth requirements.

```
Auth                       Course                       Admin
─────────                  ──────                       ─────────
POST  /auth/google         GET   /api/profile           POST  /admin/login
GET   /auth/google/config  PUT   /api/course-progress   GET   /admin
GET   /logout              GET   /api/streak            GET   /api/admin/students
                           POST  /api/streak/freeze     GET   /api/admin/student/<email>
                           POST  /api/certificate       POST  /api/admin/edit/<email>
                           GET   /api/certificates      POST  /api/admin/reset/<email>
Verify (public)            POST  /api/certificate/email POST  /api/admin/delete/<email>
─────────                                               POST  /api/admin/notify/<email>
GET  /verify/<cert_id>     Voice + push                 POST  /api/admin/broadcast
                           ──────                       GET   /admin/export/<kind>.csv
Privacy (public)           POST  /api/assistant         GET   /api/admin/live/status
─────────                  GET   /api/push/key
GET  /privacy              POST  /api/push/subscribe
```

## Security posture

- All hardcoded secrets removed; production refuses to boot if `SECRET_KEY` / `MONGO_URI` are missing
- Constant-time password comparison for admin and live-view auth
- HTML escape on every user-controlled value in HTML output (verify page, email bodies)
- JSON-encoded user data in the `/home` server-injected boot script (no string-interpolation XSS)
- `Permissions-Policy: camera=(self), microphone=(self), …` blocks every other browser API by default
- HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy on every response
- ProxyFix middleware so rate-limiting sees the real client IP behind Render's reverse proxy
- CSV-injection guard in admin exports (Excel formula payloads neutralised)
- Input size caps on every user-controlled field (prompts, push payloads, session-history entries)

## Status

Built for the WitchHunt hackathon (May 2026) by team **CODE BREAKERS** — Ayush Rai, Shubhashree B, Nagendra A S, Mahathi S, Suhas M N.

Live, deployed, in active development.

## License

MIT — see `LICENSE` if shipped, otherwise treat as MIT.

---

<div align="center">

*Made with intention, for everyday practitioners.*

🙏 *Namaste*

</div>
