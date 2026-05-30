from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session, send_from_directory
import pymongo
from bson.binary import Binary as _BsonBinary
from datetime import datetime, timedelta
from collections import defaultdict
import os
import json
import uuid
import secrets
import urllib.request
import urllib.error
import html as _html  # for HTML-escaping user-controlled values
import hmac as _hmac
import time as _time
import base64 as _b64stream

# Optional dependencies — graceful fallback if not installed in the environment.
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except Exception:
    LIMITER_AVAILABLE = False

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
    import base64 as _b64
    SENDGRID_AVAILABLE = True
except Exception:
    SENDGRID_AVAILABLE = False

try:
    from pywebpush import webpush, WebPushException
    PUSH_AVAILABLE = True
except Exception:
    PUSH_AVAILABLE = False

# Google Sign-In — verifies the ID token Google's frontend SDK gives us.
try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_AUTH_AVAILABLE = True
except Exception:
    GOOGLE_AUTH_AVAILABLE = False

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

# Admin panel — allowlist of admin emails. Default is empty so the panel is
# inaccessible until ADMIN_EMAILS is set on the server. The admin password
# also has NO fallback — if not set in env, admin login is disabled.
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

# Live-view password — protects the camera-snapshot stream from the
# student's AR session. NO fallback in code; if the env var is empty, the
# live viewer is disabled.
LIVE_VIEW_PASSWORD = os.environ.get('LIVE_VIEW_PASSWORD', '')

# Live-frame TTL — Mongo auto-deletes stale frames via TTL index above.
LIVE_FRAME_TTL = 8.0  # seconds — frames older than this count as "offline"

app = Flask(__name__)
# Behind Render / any reverse proxy, X-Forwarded-* headers carry the real
# client IP and protocol. ProxyFix tells Flask to trust them so:
#   • request.remote_addr returns the user's real IP (not the proxy)
#   • request.url uses https when the proxy says so
# Trusting only one hop is sufficient for Render.
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
except Exception:
    pass

# Flask SECRET_KEY MUST come from the environment in production. We refuse
# to start with a known default so a leaked repo can't forge sessions.
_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError('SECRET_KEY env var is required in production. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"')
    # Local dev only: generate a random one per process. Sessions reset on
    # restart, which is fine for development.
    _secret = secrets.token_hex(32)
    print('⚠ SECRET_KEY not set; using a random per-process key (sessions will not persist across restarts)')
app.secret_key = _secret
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
# Persistent sessions — supports the "stay signed in for 30 days" toggle.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# Mark cookies secure when running behind https (Render does this).
if os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True


@app.after_request
def _security_headers(resp):
    """Defense-in-depth headers applied to every response.

    • X-Content-Type-Options: blocks MIME sniffing
    • X-Frame-Options: prevents clickjacking via iframe
    • Referrer-Policy: strips full URL from outgoing referrers
    • Permissions-Policy: limits which APIs the browser will run
      (camera + microphone allowed because the AR coach uses them;
       everything else denied for safety)
    • Strict-Transport-Security: only set behind HTTPS so localhost dev
      isn't pinned. Tells browsers to never load this site over HTTP.
    """
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault(
        'Permissions-Policy',
        'camera=(self), microphone=(self), geolocation=(), payment=(), usb=(), bluetooth=()',
    )
    if os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production':
        resp.headers.setdefault(
            'Strict-Transport-Security',
            'max-age=15552000; includeSubDomains',
        )
    return resp

# Rate limiting — 30/min for /api/assistant, generous defaults elsewhere.
if LIMITER_AVAILABLE:
    limiter = Limiter(get_remote_address, app=app, default_limits=['600 per hour'], storage_uri='memory://')
    def rate_limit_assistant(f):
        return limiter.limit('30 per minute')(f)
else:
    limiter = None
    def rate_limit_assistant(f):
        return f
    print('⚠ flask-limiter not installed — rate-limiting disabled')

# MongoDB connection — the URI MUST come from the environment.
db_connected = False
mongodb_uri = os.environ.get('MONGO_URI', '')
if not mongodb_uri:
    if os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError('MONGO_URI env var is required in production.')
    print('⚠ MONGO_URI not set; database features will be disabled.')

# We use TWO databases:
#   • face_auth         — legacy DB for the old name+email login flow
#   • google_auth       — new DB exclusively for Google-Sign-In users
# Keeping them separate eliminates any chance of cross-contamination
# (stale completed_asanas / activity from the old flow leaking into a
# new Google account that happens to share the same email).
LEGACY_DB_NAME = 'face_auth'
GOOGLE_DB_NAME = 'google_auth'

try:
    if not mongodb_uri:
        raise RuntimeError('skip-connect')
    client = pymongo.MongoClient(mongodb_uri)

    # Legacy collections — unchanged for backward compatibility.
    db = client.get_database(LEGACY_DB_NAME)
    users = db.users
    certificates_col = db.certificates
    course_progress_col = db.course_progress
    preferences_col = db.preferences
    push_subs_col = db.push_subscriptions
    streak_freeze_col = db.streak_freezes

    # Google-Sign-In dedicated DB — same collection layout, separate
    # storage so a user's Google account is genuinely a clean slate.
    gdb = client.get_database(GOOGLE_DB_NAME)
    g_users = gdb.users
    g_certificates_col = gdb.certificates
    g_course_progress_col = gdb.course_progress
    g_preferences_col = gdb.preferences
    g_push_subs_col = gdb.push_subscriptions
    g_streak_freeze_col = gdb.streak_freezes

    # Admin-shared collections — feedback, audit log, etc.
    adb = client.get_database('admin_data')
    feedback_col = adb.feedback
    admin_audit_col = adb.audit
    live_frames_col = adb.live_frames
    # Multi-tenant collections — organizations, invitations.
    organizations_col = adb.organizations
    invitations_col = adb.invitations
    # Index for invitation token lookups.
    try:
        invitations_col.create_index('token', unique=True)
    except Exception:
        pass
    try:
        organizations_col.create_index('email', unique=True)
    except Exception:
        pass
    # TTL index — auto-deletes frames older than 30s. Idempotent.
    try:
        live_frames_col.create_index('expiresAt', expireAfterSeconds=0)
    except Exception:
        pass

    client.admin.command('ping')
    print(f"✓ MongoDB connected — legacy='{LEGACY_DB_NAME}', google='{GOOGLE_DB_NAME}', admin='admin_data'")
    db_connected = True
except Exception as e:
    print(f"✗ MongoDB connection failed: {e}")
    print("App will run without DB (profile features disabled)")
    users = None
    certificates_col = course_progress_col = preferences_col = None
    push_subs_col = streak_freeze_col = None
    g_users = g_certificates_col = g_course_progress_col = None
    g_preferences_col = g_push_subs_col = g_streak_freeze_col = None
    feedback_col = admin_audit_col = None
    live_frames_col = None
    organizations_col = invitations_col = None


# ─────────────────────────────────────────────────────────────
# Per-request collection routing — Google users go to google_auth,
# everyone else goes to face_auth. The session flag is set in the
# /auth/google handler, so this works automatically once the user
# has signed in via Google.
# ─────────────────────────────────────────────────────────────
def _is_google_session():
    return session.get('auth_provider') == 'google'


def get_users_col():
    return g_users if _is_google_session() else users


def get_certificates_col():
    return g_certificates_col if _is_google_session() else certificates_col


def get_course_progress_col():
    return g_course_progress_col if _is_google_session() else course_progress_col


def get_preferences_col():
    return g_preferences_col if _is_google_session() else preferences_col


def get_push_subs_col():
    return g_push_subs_col if _is_google_session() else push_subs_col


def get_streak_freeze_col():
    return g_streak_freeze_col if _is_google_session() else streak_freeze_col


# ─────────────────────────────────────────────────────────────
# Multi-tenant organization layer — registered below after the
# admin decorators are defined. See org_routes.py.
# ─────────────────────────────────────────────────────────────


def _sendgrid_send(to_email, subject, html_content):
    """Tiny shared helper: send an HTML email via SendGrid. Returns True on success.
    Used by the org-invitation flow. Falls back gracefully when SendGrid isn't
    configured — the invitation still gets created, the email just doesn't go out
    and the UI shows the magic link to copy manually.
    """
    if not SENDGRID_AVAILABLE:
        return False
    api_key = os.environ.get('SENDGRID_API_KEY')
    sender = os.environ.get('SENDGRID_FROM_EMAIL')
    if not api_key or not sender:
        return False
    try:
        msg = Mail(from_email=sender, to_emails=to_email, subject=subject, html_content=html_content)
        SendGridAPIClient(api_key).send(msg)
        return True
    except Exception as e:
        print(f'sendgrid invite-send error: {e}')
        return False


def _webpush_send(email, title, body):
    """Push a notification to a user identified by email. Returns True on success.

    Used by org-admin broadcasts. Looks up the user's saved subscription in
    either the Google or legacy push collection and sends via pywebpush.
    """
    if not PUSH_AVAILABLE:
        return False
    private = os.environ.get('VAPID_PRIVATE_KEY')
    if not private:
        return False
    sub_doc = None
    if g_push_subs_col is not None:
        sub_doc = g_push_subs_col.find_one({'email': email})
    if not sub_doc and push_subs_col is not None:
        sub_doc = push_subs_col.find_one({'email': email})
    if not sub_doc or not sub_doc.get('subscription'):
        return False
    try:
        webpush(
            subscription_info=sub_doc['subscription'],
            data=json.dumps({'title': title[:80], 'body': body[:300], 'url': '/home'}),
            vapid_private_key=private,
            vapid_claims={'sub': 'mailto:' + (os.environ.get('SENDGRID_FROM_EMAIL') or 'noreply@asanminds.app')},
        )
        return True
    except Exception as e:
        print(f'webpush send error for {email}: {e}')
        return False


# ─────────────────────────────────────────────────────────────
# ADMIN PANEL — access control + helpers
# ─────────────────────────────────────────────────────────────
from functools import wraps


def is_admin_user():
    """Returns True for any session that has unlocked the admin gate.

    Two paths in:
      1. Google sign-in as an allowlisted email + password unlock
      2. Direct admin login via /admin/login (email+password, no Google needed)
    Both set session['admin_unlocked'] = True; that's the single source of truth.
    """
    return bool(session.get('admin_unlocked') and (session.get('admin_email') or '').lower() in ADMIN_EMAILS)


def admin_required(f):
    """Decorator: redirect to admin login if not authenticated as admin."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin_user():
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return wrapper


def admin_api_required(f):
    """Same as admin_required but returns JSON 401 for API endpoints."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin_user():
            return jsonify({'error': 'Admin authentication required'}), 401
        return f(*args, **kwargs)
    return wrapper


def _audit(action, target_email='', meta=None):
    """Append an entry to the admin audit log."""
    if admin_audit_col is None:
        return
    try:
        admin_audit_col.insert_one({
            'admin_email': session.get('admin_email') or session.get('user_email'),
            'action': action,
            'target_email': target_email,
            'meta': meta or {},
            'ts': datetime.utcnow().isoformat(),
        })
    except Exception as e:
        print(f'audit log error: {e}')


def _all_user_docs():
    """Return ALL student docs across both DBs, normalised, with provider tag."""
    out = []
    if g_users is not None:
        for u in g_users.find({}):
            u.pop('_id', None)
            u['auth_provider'] = u.get('auth_provider', 'google')
            out.append(u)
    if users is not None:
        for u in users.find({}):
            u.pop('_id', None)
            u['auth_provider'] = u.get('auth_provider', 'email')
            out.append(u)
    return out


def _student_summary(u):
    """Build a one-row summary for a student (for the admin list)."""
    email = u.get('email', '')
    activity = u.get('activity_log', []) or []
    last_active = max(activity) if activity else None
    # Streak quick-calc.
    best = 0
    cur = 0
    prev = None
    for d in sorted(activity):
        try:
            t = datetime.fromisoformat(d).date()
        except Exception:
            continue
        if prev and (t - prev).days == 1:
            cur += 1
        else:
            cur = 1
        if cur > best:
            best = cur
        prev = t
    # Course completion count.
    sems_completed = 0
    has_master = False
    is_google = u.get('auth_provider') == 'google'
    cp_col = g_course_progress_col if is_google else course_progress_col
    cert_col = g_certificates_col if is_google else certificates_col
    if cp_col is not None:
        cp_doc = cp_col.find_one({'email': email}) or {}
        progress = (cp_doc.get('progress') or {}).get('courses') or {}
        for c in progress.values():
            if c.get('completed'):
                sems_completed += 1
    if cert_col is not None:
        master = cert_col.find_one({'email': email, 'courseId': 'master'})
        has_master = bool(master)
    completed_asanas = u.get('completed_asanas', {}) or {}
    total_sessions = sum(int(v or 0) for v in completed_asanas.values())
    return {
        'email': email,
        'name': u.get('name', ''),
        'picture': u.get('picture', ''),
        'auth_provider': u.get('auth_provider', 'email'),
        'created_at': u['created_at'].isoformat() if hasattr(u.get('created_at'), 'isoformat') else (u.get('created_at') or None),
        'last_active': last_active,
        'active_days': len(activity),
        'best_streak': best,
        'total_sessions': total_sessions,
        'poses_learned': len(completed_asanas),
        'sems_completed': sems_completed,
        'has_master': has_master,
        'role': u.get('role', 'student'),
        'organization_email': u.get('organizationEmail') or u.get('organization_email') or '',
        'academic': u.get('academic') or {},
        'paid_status': u.get('paidStatus') or u.get('paid_status') or 'unknown',
    }


# ─────────────────────────────────────────────────────────────
# MULTI-TENANT (orgs, invitations, sub-admin) helpers
# ─────────────────────────────────────────────────────────────
TEST_ORG_EMAIL = 'test@asanminds.local'


def _ensure_test_org():
    """Make sure the system 'test' organization exists. Existing legacy users
    (those without a role) are mapped to this org so they keep working."""
    if organizations_col is None:
        return
    existing = organizations_col.find_one({'email': TEST_ORG_EMAIL})
    if existing:
        return
    try:
        organizations_col.insert_one({
            'email': TEST_ORG_EMAIL,
            'name': 'AsanMinds Test Org',
            'domain': '*',  # accepts any email
            'studentCap': 9999,
            'studentsEnrolled': 0,
            'paid': True,
            'paidUntil': '2099-12-31T00:00:00',
            'batches': ['test'],
            'branches': [{'code': 'TEST', 'name': 'Test users'}],
            'sections': ['T'],
            'system': True,  # hidden from regular org list
            'createdAt': datetime.utcnow().isoformat(),
            'createdByAdmin': 'system',
        })
        print('✓ Test organization created')
    except Exception as e:
        print(f'test org init failed: {e}')


def _migrate_legacy_users():
    """Run once on boot: any user without a role becomes a student of the
    test org. Idempotent — safe to run on every boot."""
    if not db_connected:
        return
    today = datetime.utcnow().isoformat()
    migrated = 0
    for col, default_provider in ((g_users, 'google'), (users, 'email')):
        if col is None:
            continue
        try:
            res = col.update_many(
                {'role': {'$exists': False}},
                {'$set': {
                    'role': 'student',
                    'organizationEmail': TEST_ORG_EMAIL,
                    'academic': {'batch': 'test', 'branch': 'TEST', 'section': 'T'},
                    'migrated_at': today,
                }},
            )
            migrated += res.modified_count
        except Exception as e:
            print(f'legacy migration error: {e}')
    if migrated:
        print(f'✓ Migrated {migrated} legacy user(s) into the test org')


_ensure_test_org()
_migrate_legacy_users()


def is_org_admin():
    """Returns True if the current session belongs to an organization sub-admin."""
    return bool(
        session.get('logged_in') and
        session.get('role') == 'org_admin' and
        session.get('user_email') and
        session.get('organization_email')
    )


def org_admin_required(f):
    """Decorator: 401 if not signed in as an org-admin."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_org_admin():
            return jsonify({'error': 'Organization admin sign-in required'}), 401
        return f(*args, **kwargs)
    return wrapper


def _current_org_email():
    """The org email scoping the current org-admin's session."""
    return (session.get('organization_email') or '').lower()


def _user_doc_by_email(email):
    """Find a user across both DBs."""
    em = (email or '').lower()
    for col in (g_users, users):
        if col is not None:
            u = col.find_one({'email': em})
            if u:
                return u, col
    return None, None


def _ensure_target_in_my_org(target_email):
    """Guardrail for org-admin endpoints: only allow operating on students
    whose organizationEmail matches mine."""
    me = _current_org_email()
    if not me:
        return False
    u, _ = _user_doc_by_email(target_email)
    if not u:
        return False
    return (u.get('organizationEmail') or '').lower() == me


def _compute_current_semester(joining_year):
    """Auto-progression: 6th-month rollover (July) bumps the sem.

    Sem 1 starts in the join year's August (month 8 onward).
    Each calendar year past joining adds 2 sems if month >= July, else 1 sem.
    Sem 1 -> 8, capped at 8.
    """
    try:
        join = int(joining_year)
    except Exception:
        return 1
    now = datetime.utcnow()
    years_past = now.year - join
    sem = 1 + max(0, years_past) * 2
    if now.month >= 7:
        sem += 1
    return max(1, min(8, sem))


def _audit_org(action, target_email='', meta=None):
    """Same as _audit but tags the action with the org_admin's identity."""
    if admin_audit_col is None:
        return
    try:
        admin_audit_col.insert_one({
            'admin_email': session.get('user_email'),
            'admin_role': session.get('role'),
            'organization_email': session.get('organization_email'),
            'action': action,
            'target_email': target_email,
            'meta': meta or {},
            'ts': datetime.utcnow().isoformat(),
        })
    except Exception:
        pass


# Updated INDEX_HTML (with /home redirects)
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AsanMinds — AI yoga coaching for institutions and individuals</title>
    <meta name="description" content="AsanMinds is an AI-guided yoga platform with real-time pose correction, voice coaching, six-semester courseware, and institutional dashboards. Built for colleges, scaled for everyone.">
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#0F3D2E">
    <link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="192x192" href="/assets/brand/logo-192.png">
    <link rel="icon" type="image/png" sizes="512x512" href="/assets/brand/logo-512.png">
    <link rel="icon" type="image/svg+xml" href="/assets/brand/favicon.svg">
    <link rel="alternate icon" type="image/png" href="/assets/brand/logo-192.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #F5F2EB;
            --surface: #FFFFFF;
            --surface-2: #EEE9DE;
            --surface-3: #E0D9C8;
            --border: #D4CCB8;
            --text-1: #14120E;
            --text-2: #4A453B;
            --text-3: #7A7364;
            --text-4: #A8A294;
            --primary: #0F3D2E;
            --primary-2: #1F5A44;
            --primary-3: #6FA089;
            --primary-4: #C7DBCE;
            --accent: #C2552F;
            --accent-soft: #F6DACB;
            --gold: #E0A23F;
            --gold-soft: #F3D58C;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
            background: var(--bg);
            color: var(--text-1);
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            line-height: 1.55;
        }
        body { min-height: 100vh; }
        a { color: inherit; text-decoration: none; }
        img { max-width: 100%; display: block; }
        .font-display { font-family: 'Fraunces', ui-serif, Georgia, serif; letter-spacing: -0.02em; font-optical-sizing: auto; }
        .kicker { font-family: 'Inter', sans-serif; font-weight: 600; font-size: 11px; line-height: 14px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--accent); }

        /* Container */
        .wrap { max-width: 1200px; margin: 0 auto; padding: 0 24px; }

        /* Top nav */
        .topbar {
            position: sticky; top: 0; z-index: 50;
            background: rgba(245, 242, 235, 0.92);
            backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
            border-bottom: 1px solid rgba(26,24,20,0.06);
        }
        .topbar-inner { display: flex; align-items: center; justify-content: space-between; height: 72px; }
        .brand { display: flex; align-items: center; gap: 10px; }
        .brand-mark { width: 32px; height: 32px; border-radius: 8px; display: block; flex-shrink: 0; background: transparent; }
        .brand-name { font-family: 'Fraunces', serif; font-size: 20px; font-weight: 500; letter-spacing: -0.01em; }
        .brand-name em { font-style: normal; color: var(--text-3); font-size: 13px; font-weight: 400; }
        .nav-links { display: none; gap: 28px; align-items: center; }
        .nav-links a { color: var(--text-2); font-size: 14px; font-weight: 500; transition: color .2s; }
        .nav-links a:hover { color: var(--primary); }
        @media (min-width: 880px) { .nav-links { display: flex; } }

        /* Buttons */
        .btn {
            display: inline-flex; align-items: center; justify-content: center; gap: 8px;
            border: 0; border-radius: 9999px; cursor: pointer;
            font-family: 'Inter', sans-serif; font-weight: 600; font-size: 14px;
            padding: 0 22px; height: 46px;
            transition: transform .12s ease, background .2s ease, box-shadow .2s ease;
            text-decoration: none;
        }
        .btn:active { transform: scale(0.98); }
        .btn-primary { background: var(--primary); color: var(--bg); }
        .btn-primary:hover { background: var(--primary-2); box-shadow: 0 8px 24px rgba(15,61,46,0.18); }
        .btn-accent { background: var(--accent); color: var(--bg); }
        .btn-accent:hover { filter: brightness(1.05); box-shadow: 0 8px 24px rgba(194,85,47,0.22); }
        .btn-outline { background: transparent; color: var(--text-1); border: 1.5px solid var(--text-1); }
        .btn-outline:hover { background: var(--text-1); color: var(--bg); }
        .btn-ghost { background: var(--surface-2); color: var(--text-1); }
        .btn-ghost:hover { background: var(--surface-3); }
        .btn-sm { height: 40px; padding: 0 18px; font-size: 13px; }
        .btn-lg { height: 56px; padding: 0 32px; font-size: 15px; }

        /* HERO */
        .hero { padding: 64px 0 96px; position: relative; overflow: hidden; }
        .hero-grid { display: grid; gap: 56px; align-items: center; }
        @media (min-width: 920px) { .hero-grid { grid-template-columns: 1.15fr 1fr; gap: 80px; } }
        .hero h1 {
            font-family: 'Fraunces', serif;
            font-size: clamp(44px, 6.5vw, 80px);
            font-weight: 300;
            line-height: 1.02;
            letter-spacing: -0.035em;
            color: var(--text-1);
            margin-top: 16px;
        }
        .hero h1 em { font-style: italic; color: var(--accent); font-weight: 400; }
        .hero p.lede { font-size: 18px; color: var(--text-2); margin: 24px 0 36px; max-width: 540px; line-height: 1.6; }
        .hero-cta { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }
        .hero-stats { margin-top: 40px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 32px; max-width: 480px; }
        .hero-stats > div span { display: block; font-family: 'Fraunces', serif; font-size: 32px; font-weight: 400; color: var(--primary); letter-spacing: -0.02em; }
        .hero-stats > div p { font-size: 12px; color: var(--text-3); margin-top: 4px; line-height: 1.4; }

        .hero-art {
            position: relative; aspect-ratio: 4/5; max-width: 480px; justify-self: center;
            border-radius: 32px; overflow: hidden; background: var(--primary);
            box-shadow: 0 30px 80px rgba(15,61,46,0.35);
        }
        .hero-art::before {
            content: ''; position: absolute; inset: 0;
            background: linear-gradient(160deg, rgba(224,162,63,0.18) 0%, rgba(15,61,46,0) 50%, rgba(194,85,47,0.16) 100%);
            z-index: 2;
        }
        .hero-art img { width: 100%; height: 100%; object-fit: cover; opacity: 0.78; }
        .hero-art .badge {
            position: absolute; top: 24px; left: 24px; z-index: 3;
            background: rgba(245,242,235,0.95); padding: 8px 14px; border-radius: 9999px;
            font-size: 11px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--primary);
        }
        .hero-art .score-card {
            position: absolute; bottom: 24px; left: 24px; right: 24px; z-index: 3;
            background: rgba(15,61,46,0.85); backdrop-filter: blur(8px);
            border: 1px solid rgba(245,242,235,0.18); border-radius: 18px;
            padding: 16px 18px; color: var(--bg);
        }
        .score-card .row { display: flex; justify-content: space-between; align-items: center; }
        .score-card .label { font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
        .score-card .value { font-family: 'Fraunces', serif; font-size: 28px; font-weight: 400; color: var(--bg); }
        .score-card .bar { height: 4px; background: rgba(245,242,235,0.18); border-radius: 999px; margin-top: 10px; overflow: hidden; }
        .score-card .bar > div { width: 86%; height: 100%; background: linear-gradient(90deg, var(--gold) 0%, var(--primary-3) 100%); border-radius: 999px; }
        .score-card .cue { font-size: 12px; color: var(--primary-4); margin-top: 8px; }

        /* Trust strip */
        .trust {
            padding: 32px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
            background: var(--surface-2);
        }
        .trust-inner { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 24px; }
        .trust p { font-size: 11px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--text-3); font-weight: 600; }
        .trust ul { list-style: none; display: flex; flex-wrap: wrap; gap: 28px; }
        .trust li { font-family: 'Fraunces', serif; font-size: 17px; color: var(--text-2); font-weight: 400; }

        /* Section */
        .section { padding: 96px 0; }
        .section-head { max-width: 720px; margin: 0 auto 56px; text-align: center; }
        .section-head h2 { font-family: 'Fraunces', serif; font-size: clamp(34px, 4.5vw, 54px); font-weight: 300; line-height: 1.1; letter-spacing: -0.025em; margin-top: 14px; }
        .section-head h2 em { color: var(--accent); font-style: italic; font-weight: 400; }
        .section-head p { color: var(--text-2); margin-top: 18px; font-size: 17px; line-height: 1.6; }

        /* Feature grid */
        .features { display: grid; gap: 20px; grid-template-columns: 1fr; }
        @media (min-width: 720px) { .features { grid-template-columns: repeat(2, 1fr); } }
        @media (min-width: 1040px) { .features { grid-template-columns: repeat(3, 1fr); } }
        .feat-card {
            background: var(--surface); border: 1px solid var(--border); border-radius: 24px;
            padding: 28px; display: flex; flex-direction: column; gap: 14px;
            transition: transform .3s ease, box-shadow .3s ease;
        }
        .feat-card:hover { transform: translateY(-4px); box-shadow: 0 20px 50px rgba(20,18,14,0.10); }
        .feat-icon {
            width: 48px; height: 48px; border-radius: 14px;
            display: flex; align-items: center; justify-content: center;
            background: var(--primary); color: var(--gold);
        }
        .feat-icon svg { width: 24px; height: 24px; }
        .feat-card.alt .feat-icon { background: var(--accent); color: var(--bg); }
        .feat-card.gold .feat-icon { background: var(--gold); color: var(--primary); }
        .feat-card h3 { font-family: 'Fraunces', serif; font-size: 22px; font-weight: 400; line-height: 1.2; letter-spacing: -0.01em; }
        .feat-card p { color: var(--text-2); font-size: 14.5px; line-height: 1.6; }

        /* Steps */
        .steps { display: grid; gap: 28px; counter-reset: step; }
        @media (min-width: 880px) { .steps { grid-template-columns: repeat(3, 1fr); } }
        .step {
            background: var(--surface-2); border-radius: 24px; padding: 32px;
            border: 1px solid var(--border); position: relative;
        }
        .step::before {
            counter-increment: step;
            content: counter(step, decimal-leading-zero);
            font-family: 'Fraunces', serif; font-size: 64px; font-weight: 300;
            color: var(--accent); line-height: 1; letter-spacing: -0.03em; opacity: .9;
        }
        .step h3 { font-family: 'Fraunces', serif; font-size: 22px; font-weight: 400; margin: 12px 0 8px; }
        .step p { color: var(--text-2); font-size: 14.5px; line-height: 1.6; }

        /* Institution band */
        .inst {
            background: var(--primary); color: var(--bg); border-radius: 32px;
            padding: 64px 40px; position: relative; overflow: hidden;
            display: grid; gap: 32px;
        }
        @media (min-width: 880px) { .inst { grid-template-columns: 1.2fr 1fr; align-items: center; padding: 80px; } }
        .inst::before {
            content: ''; position: absolute; top: -120px; right: -100px;
            width: 360px; height: 360px; border-radius: 9999px;
            background: rgba(224,162,63,0.18); filter: blur(20px); pointer-events: none;
        }
        .inst::after {
            content: ''; position: absolute; bottom: -80px; left: -60px;
            width: 280px; height: 280px; border-radius: 9999px;
            background: rgba(194,85,47,0.15); filter: blur(20px); pointer-events: none;
        }
        .inst > * { position: relative; z-index: 1; }
        .inst h2 { font-family: 'Fraunces', serif; font-size: clamp(32px, 4vw, 48px); font-weight: 300; line-height: 1.1; letter-spacing: -0.025em; }
        .inst h2 em { color: var(--gold); font-style: italic; font-weight: 400; }
        .inst p { color: var(--primary-4); margin-top: 20px; font-size: 16px; line-height: 1.65; max-width: 560px; }
        .inst ul { list-style: none; margin-top: 24px; display: grid; gap: 12px; }
        .inst ul li { display: flex; gap: 12px; align-items: flex-start; color: var(--bg); font-size: 14px; }
        .inst ul li::before { content: '✓'; color: var(--gold); font-weight: 700; }
        .inst-card {
            background: rgba(245,242,235,0.06); border: 1px solid rgba(245,242,235,0.12);
            border-radius: 22px; padding: 28px;
        }
        .inst-card h4 { font-family: 'Fraunces', serif; font-size: 18px; color: var(--gold); font-weight: 400; }
        .inst-card .num { font-family: 'Fraunces', serif; font-size: 48px; font-weight: 300; line-height: 1; margin: 16px 0 8px; color: var(--bg); letter-spacing: -0.02em; }
        .inst-card p { font-size: 13px; color: var(--primary-4); margin-top: 6px; }
        .inst-stats { display: grid; grid-template-columns: repeat(2,1fr); gap: 16px; margin-top: 18px; }

        /* Final CTA */
        .final-cta { text-align: center; padding: 96px 24px; }
        .final-cta h2 { font-family: 'Fraunces', serif; font-size: clamp(40px, 6vw, 72px); font-weight: 300; line-height: 1.05; letter-spacing: -0.03em; max-width: 880px; margin: 0 auto; }
        .final-cta h2 em { font-style: italic; color: var(--accent); font-weight: 400; }
        .final-cta p { color: var(--text-2); font-size: 17px; margin: 24px auto 36px; max-width: 600px; }
        .final-cta .cta-row { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }

        /* Footer */
        footer { background: var(--surface-2); border-top: 1px solid var(--border); padding: 48px 0 32px; }
        .foot-grid { display: grid; gap: 32px; grid-template-columns: 1fr; }
        @media (min-width: 720px) { .foot-grid { grid-template-columns: 2fr 1fr 1fr; } }
        .foot-grid h5 { font-size: 11px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--text-3); font-weight: 600; margin-bottom: 14px; }
        .foot-grid a { display: block; color: var(--text-2); font-size: 14px; padding: 4px 0; }
        .foot-grid a:hover { color: var(--primary); }
        .foot-bottom { border-top: 1px solid var(--border); margin-top: 36px; padding-top: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--text-3); }

        /* Sign-in modal */
        .modal-back {
            position: fixed; inset: 0; z-index: 100;
            background: rgba(20,18,14,0.55); backdrop-filter: blur(8px);
            display: none; align-items: center; justify-content: center; padding: 16px;
        }
        .modal-back.open { display: flex; }
        .modal {
            background: var(--bg); border-radius: 28px; max-width: 440px; width: 100%;
            border: 1px solid var(--border); padding: 36px 32px;
            box-shadow: 0 40px 100px rgba(20,18,14,0.30);
            position: relative;
        }
        .modal h3 { font-family: 'Fraunces', serif; font-size: 32px; font-weight: 300; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 8px; }
        .modal p.sub { color: var(--text-2); font-size: 14.5px; line-height: 1.6; margin-bottom: 28px; }
        .modal .gh-host { display: flex; justify-content: center; min-height: 48px; }
        .modal .close-x {
            position: absolute; top: 14px; right: 14px;
            background: var(--surface-2); border: 0; width: 36px; height: 36px;
            border-radius: 9999px; cursor: pointer; color: var(--text-2); font-size: 18px;
        }
        .modal .help { margin-top: 22px; padding-top: 22px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-3); line-height: 1.5; }
        .modal .err { margin-top: 16px; padding: 12px 14px; background: var(--accent-soft); border: 1px solid var(--accent); border-radius: 14px; font-size: 13px; color: var(--text-1); display: none; }

        /* Full-screen redirect curtain — covers the cream→white flash
           between sign-in and /home so the transition feels instant. */
        .loader-back {
            position: fixed; inset: 0; z-index: 200;
            background: var(--primary);
            display: none; align-items: center; justify-content: center;
            flex-direction: column; gap: 18px;
            opacity: 0; transition: opacity .25s ease;
        }
        .loader-back.on { display: flex; opacity: 1; }
        .loader-back .brand-row { display: flex; align-items: center; gap: 12px; opacity: .92; }
        .loader-back .brand-row .mark { width: 36px; height: 36px; border-radius: 8px; display: block; }
        .loader-back .brand-row .name { font-family: 'Fraunces', serif; font-size: 22px; font-weight: 400; color: var(--bg); letter-spacing: -0.01em; }
        .spinner { width: 32px; height: 32px; border-radius: 9999px; border: 3px solid rgba(245,242,235,0.18); border-top-color: var(--gold); animation: spin 0.8s linear infinite; }
        .loader-back .label { font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>

<header class="topbar">
  <div class="wrap topbar-inner">
    <a href="/" class="brand">
      <img class="brand-mark" src="/assets/brand/logo1.png" alt="AsanMinds" width="32" height="32">
      <span class="brand-name">sunday <em>· asanminds</em></span>
    </a>
    <nav class="nav-links" aria-label="Primary">
      <a href="#features">Features</a>
      <a href="#how">How it works</a>
      <a href="#institutions">For institutions</a>
    </nav>
    <div style="display:flex; gap:10px; align-items:center;">
      <button class="btn btn-ghost btn-sm" data-open-signin>Sign in</button>
      <button class="btn btn-primary btn-sm" data-open-signin>Begin</button>
    </div>
  </div>
</header>

<!-- HERO -->
<section class="hero">
  <div class="wrap hero-grid">
    <div>
      <span class="kicker">Six semesters · twenty asanas · one calmer you</span>
      <h1>Yoga that <em>watches</em>, listens, and teaches you back.</h1>
      <p class="lede">AsanMinds is an AI yoga coach for institutions and individuals. Real-time pose correction in your browser, voice guidance that answers questions, and a six-semester progression that earns a certificate worth showing.</p>
      <div class="hero-cta">
        <button class="btn btn-primary btn-lg" data-open-signin>Begin your practice →</button>
        <a class="btn btn-outline btn-lg" href="#how">See how it works</a>
      </div>
      <div class="hero-stats">
        <div><span>20</span><p>guided asanas with anatomical cues</p></div>
        <div><span>6</span><p>semesters of structured progression</p></div>
        <div><span>0</span><p>downloads — runs in any browser</p></div>
      </div>
    </div>
    <div class="hero-art">
      <span class="badge">Live AR session</span>
      <img src="/assets/poses/vrikshasana.png" alt="Vrikshasana — tree pose">
      <div class="score-card">
        <div class="row">
          <span class="label">Alignment</span>
          <span class="value">86%</span>
        </div>
        <div class="bar"><div></div></div>
        <p class="cue">Lift the standing leg's arch · soften the shoulders</p>
      </div>
    </div>
  </div>
</section>

<!-- TRUST STRIP -->
<div class="trust">
  <div class="wrap trust-inner">
    <p>Onboarding institutions across India</p>
    <ul>
      <li>VVCE, Mysuru</li>
      <li>· Pilot programmes 2024</li>
      <li>· FERPA-aligned data isolation</li>
    </ul>
  </div>
</div>

<!-- FEATURE GRID -->
<section class="section" id="features">
  <div class="wrap">
    <div class="section-head">
      <span class="kicker">What's inside</span>
      <h2>Everything a yoga programme should have, <em>nothing</em> it shouldn't.</h2>
      <p>Pose correction, voice coaching, library, courseware, certificates and analytics — built into one calm cream-paper interface.</p>
    </div>
    <div class="features">
      <div class="feat-card">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z"/></svg>
        </div>
        <h3>Real-time AR coach</h3>
        <p>TensorFlow.js MoveNet runs on-device. We score 17 keypoint angles every frame, draw the corrective overlay, and tell you exactly which limb to move where.</p>
      </div>
      <div class="feat-card alt">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
        </div>
        <h3>AI voice assistant</h3>
        <p>Hands-free coaching. Ask "what muscles does this work?" or say "next pose" — Sunday answers in your ear so you stay on the mat.</p>
      </div>
      <div class="feat-card gold">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2zM22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>
        </div>
        <h3>Pose library, deeply annotated</h3>
        <p>Each asana has Sanskrit meaning, alignment cues, common mistakes, modifications, philosophy notes, and pairs-naturally-with hints.</p>
      </div>
      <div class="feat-card">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg>
        </div>
        <h3>Certified six-semester course</h3>
        <p>Pass the AR test plus quiz for every pose. Progress is recorded, semesters auto-roll, and certificates are issued as cryptographically-signed PDFs.</p>
      </div>
      <div class="feat-card alt">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-5"/></svg>
        </div>
        <h3>Institutional analytics</h3>
        <p>Cohort-wise dashboards: by batch, branch, section. See who's stuck, who's ahead, and who needs a nudge — without violating any student's privacy.</p>
      </div>
      <div class="feat-card gold">
        <div class="feat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        </div>
        <h3>Bulk import & roster sync</h3>
        <p>Drop an Excel sheet of students with batch + branch + section. Validate, preview, then send a single click of magic-link invitations.</p>
      </div>
    </div>
  </div>
</section>

<!-- HOW IT WORKS -->
<section class="section" id="how" style="background: var(--surface-2);">
  <div class="wrap">
    <div class="section-head">
      <span class="kicker">How it works</span>
      <h2>From an empty mat to <em>aligned</em> in three steps.</h2>
      <p>No app to download. Open AsanMinds in your browser, point your camera, and the AI handles the rest.</p>
    </div>
    <div class="steps">
      <div class="step">
        <h3>Pick a pose</h3>
        <p>Browse the library by difficulty or jump straight into your current semester. Every pose has alignment cues and a reference photo.</p>
      </div>
      <div class="step">
        <h3>Camera + AR</h3>
        <p>Allow camera access. The AR coach overlays a corrective skeleton on your live feed. Score updates 30× per second.</p>
      </div>
      <div class="step">
        <h3>Hold, score, advance</h3>
        <p>Hit 80% alignment for the required hold. Take the quiz. Pose unlocked. Semester progresses. Certificate when complete.</p>
      </div>
    </div>
  </div>
</section>

<!-- FOR INSTITUTIONS -->
<section class="section" id="institutions">
  <div class="wrap">
    <div class="inst">
      <div>
        <span class="kicker" style="color: var(--gold);">For colleges & wellness programmes</span>
        <h2>Roll out yoga across your <em>whole campus</em> in a week.</h2>
        <p>AsanMinds Institutional gives you an admin panel scoped to your domain, bulk Excel onboarding, broadcast announcements, cohort analytics, and per-student progress tracking. We handle hosting, data isolation, and certificate verification.</p>
        <ul>
          <li>One-time annual licence per organisation, scoped to a domain</li>
          <li>Multi-tenant DB — your students' data never touches another org</li>
          <li>Sub-admin sign-in via Google · no passwords to manage</li>
          <li>Branded certificates carrying your institution's name</li>
          <li>Excel template for batch + branch + section onboarding</li>
        </ul>
        <div style="margin-top:32px; display:flex; gap:14px; flex-wrap:wrap;">
          <a class="btn btn-accent" href="mailto:pgayushrai@gmail.com?subject=AsanMinds%20for%20our%20institution">Talk to our team →</a>
          <button class="btn btn-outline" style="color:var(--bg); border-color:var(--bg);" data-open-signin>Sub-admin sign in</button>
        </div>
      </div>
      <div class="inst-card">
        <h4>VVCE pilot snapshot</h4>
        <div class="inst-stats">
          <div><div class="num">1,000</div><p>seats provisioned per semester</p></div>
          <div><div class="num">6×</div><p>semester progression supported</p></div>
          <div><div class="num">≤2 wk</div><p>typical onboarding to first cohort</p></div>
          <div><div class="num">20</div><p>asanas across foundation to advanced</p></div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- FINAL CTA -->
<section class="final-cta" id="get-started">
  <div class="wrap">
    <span class="kicker">Get started</span>
    <h2>Whether you're <em>one</em> mat or <em>a thousand</em>.</h2>
    <p>Individuals begin a guided practice with their Google account. Institutions get a custom rollout with admin tooling and cohort analytics. The AR coach is the same in both.</p>
    <div class="cta-row">
      <button class="btn btn-primary btn-lg" data-open-signin>Begin your practice →</button>
      <a class="btn btn-outline btn-lg" href="mailto:pgayushrai@gmail.com?subject=AsanMinds%20for%20our%20institution">Bring it to my college</a>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <div class="brand" style="margin-bottom:12px;">
          <img class="brand-mark" src="/assets/brand/logo1.png" alt="AsanMinds" width="32" height="32">
          <span class="brand-name">sunday <em>· asanminds</em></span>
        </div>
        <p style="color: var(--text-3); font-size: 13.5px; max-width: 360px; line-height: 1.6;">An AI yoga programme that meets you where you are. Built calm, on purpose.</p>
      </div>
      <div>
        <h5>Product</h5>
        <a href="#features">Features</a>
        <a href="#how">How it works</a>
        <a href="#institutions">For institutions</a>
        <a href="#get-started">Get started</a>
      </div>
      <div>
        <h5>Account</h5>
        <a href="#" data-open-signin>Sign in</a>
        <a href="#" data-open-signin>Sub-admin access</a>
        <a href="/admin/login">Internal admin</a>
        <a href="mailto:pgayushrai@gmail.com">Contact us</a>
      </div>
    </div>
    <div class="foot-bottom">
      <span>© <span id="yr"></span> AsanMinds · sunday.</span>
      <span>Made in India · cream paper, forest green</span>
    </div>
  </div>
</footer>

<!-- Sign-in modal -->
<div class="modal-back" id="signin-modal" role="dialog" aria-modal="true" aria-labelledby="signin-h">
  <div class="modal">
    <button class="close-x" data-close-signin aria-label="Close">×</button>
    <span class="kicker">Welcome back</span>
    <h3 id="signin-h" style="margin-top:8px;">Sign in to continue.</h3>
    <p class="sub">Use the same Google account your invitation was sent to. Brand-new? Ask your organization to send you a magic link.</p>
    <div id="g-host" class="gh-host"></div>
    <p id="signin-err" class="err"></p>
    <div class="help">
      Looking for the internal admin panel? <a href="/admin/login" style="color: var(--primary); font-weight: 600;">Sign in here</a>.<br>
      Have an invitation link in your email? Just click it — sign-in happens automatically.
    </div>
  </div>
</div>

<!-- Redirect curtain — forest green, branded, covers the post-signin transition -->
<div class="loader-back" id="loader">
  <div class="brand-row">
    <img class="mark" src="/assets/brand/logo1.png" alt="AsanMinds" width="36" height="36">
    <span class="name">sunday <span style="color: var(--gold-soft); font-weight: 400; font-size: 14px;">· asanminds</span></span>
  </div>
  <div class="spinner"></div>
  <p class="label">Preparing your practice</p>
</div>

<script>
    // Year stamp
    document.getElementById('yr').textContent = new Date().getFullYear();

    // Service worker
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/sw.js').catch(function () {});
        });
    }

    // Modal controls
    var modal = document.getElementById('signin-modal');
    var loader = document.getElementById('loader');
    var googleReady = false;
    var googleClientId = null;

    function openSignin() {
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
        // Pre-warm /home so the post-signin redirect feels instant. The
        // browser DNS-resolves and opens the connection now, before the
        // user has even clicked the Google button.
        try {
            if (!document.getElementById('home-prefetch')) {
                var pf = document.createElement('link');
                pf.id = 'home-prefetch';
                pf.rel = 'prefetch';
                pf.href = '/home';
                document.head.appendChild(pf);
            }
        } catch (e) { /* prefetch is best-effort */ }
        // Lazy-render Google button on first open.
        ensureGoogle().then(function () {
            if (!googleReady) return;
            var host = document.getElementById('g-host');
            host.innerHTML = '';
            try {
                google.accounts.id.renderButton(host, {
                    theme: 'outline', size: 'large', text: 'continue_with',
                    shape: 'pill', logo_alignment: 'left', width: 320
                });
                google.accounts.id.prompt();
            } catch (e) { console.warn('Google button render failed:', e); }
        });
    }
    function closeSignin() {
        modal.classList.remove('open');
        document.body.style.overflow = '';
    }
    document.querySelectorAll('[data-open-signin]').forEach(function (b) {
        b.addEventListener('click', function (e) { e.preventDefault(); openSignin(); });
    });
    document.querySelectorAll('[data-close-signin]').forEach(function (b) {
        b.addEventListener('click', closeSignin);
    });
    modal.addEventListener('click', function (e) { if (e.target === modal) closeSignin(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeSignin(); });

    function showLoader(on) { loader.classList.toggle('on', !!on); }

    // Google credential handler — drop the modal immediately, raise the
    // forest curtain, and replace the URL so /home isn't kept on top of
    // the back-stack pointing at the cream landing.
    window.handleGoogleCredential = async function (response) {
        // Hide the sign-in modal the moment the credential is in flight —
        // before the network round-trip — so users never see it sitting
        // there mid-redirect.
        closeSignin();
        showLoader(true);
        try {
            var res = await fetch('/auth/google', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ credential: response.credential }),
            });
            var data = await res.json();
            if (data.success) {
                // location.replace so Back doesn't bounce them out of /home
                // back onto the marketing site mid-flow.
                window.location.replace('/home');
                return;
            }
            showLoader(false);
            openSignin(); // bring the modal back so they can retry
            var err = document.getElementById('signin-err');
            err.textContent = data.error || 'Google sign-in failed.';
            err.style.display = 'block';
        } catch (e) {
            showLoader(false);
            openSignin();
            var err2 = document.getElementById('signin-err');
            err2.textContent = 'Connection error. Please try again.';
            err2.style.display = 'block';
        }
    };

    // Lazy-init GIS
    var gisPromise = null;
    function ensureGoogle() {
        if (gisPromise) return gisPromise;
        gisPromise = (async function () {
            try {
                var r = await fetch('/auth/google/config');
                var cfg = r.ok ? await r.json() : {};
                if (!cfg.enabled || !cfg.clientId) {
                    var err = document.getElementById('signin-err');
                    err.textContent = 'Google sign-in is not configured on this server.';
                    err.style.display = 'block';
                    return;
                }
                googleClientId = cfg.clientId;
                await new Promise(function (resolve, reject) {
                    var s = document.createElement('script');
                    s.src = 'https://accounts.google.com/gsi/client';
                    s.async = true; s.defer = true;
                    s.onload = resolve; s.onerror = reject;
                    document.head.appendChild(s);
                });
                google.accounts.id.initialize({
                    client_id: googleClientId,
                    callback: window.handleGoogleCredential,
                    auto_select: false,
                    use_fedcm_for_prompt: true,
                });
                googleReady = true;
            } catch (e) {
                console.warn('Google sign-in unavailable:', e);
            }
        })();
        return gisPromise;
    }

    // Smooth scroll for anchors
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
        a.addEventListener('click', function (e) {
            var id = a.getAttribute('href');
            if (id && id.length > 1 && document.querySelector(id)) {
                e.preventDefault();
                document.querySelector(id).scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });
</script>
</body>
</html>
"""

@app.route('/')
def index():
    # If the visitor is already signed in, send them to the right
    # surface so the PWA's start_url ('/') lands them in the app
    # (not on the marketing landing) when they tap the installed icon.
    if session.get('logged_in'):
        if session.get('role') == 'org_admin':
            return redirect('/org')
        if session.get('role') == 'super_admin':
            return redirect('/admin')
        return redirect(url_for('home'))
    return render_template_string(INDEX_HTML)

@app.route('/main')
def main_alias():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    return redirect(url_for('home'))

@app.route('/home')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    # Org-admins shouldn't see the student app's home — route them to /org.
    if session.get('role') == 'org_admin':
        return redirect('/org')
    if not os.path.exists('main.html'):
        return "Error: main.html not found in app directory. Place it here.", 500
    
    with open('main.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Inject API Key, Source URL, and the AUTHENTICATED user's identity so
    # the page boots with truth from the server session — not from a cached
    # localStorage left behind by a previous user on this device.
    #
    # All values are JSON-encoded with json.dumps() — this guarantees no
    # injection is possible regardless of what's in the user's name, email,
    # or picture URL. JSON strings are valid JS string literals.
    site_url = request.url_root.rstrip('/')
    inj_data = {
        'gemini_api_key': os.environ.get('GEMINI_API_KEY', ''),
        'asana_mind_url': site_url,
        'user_email': session.get('user_email') or '',
        'user_name': session.get('user_name') or '',
        'user_picture': session.get('picture') or '',
    }

    injection = """
    <script>
        window.__gemini_api_key = """ + json.dumps(inj_data['gemini_api_key']) + """;
        window.__asana_mind_url = """ + json.dumps(inj_data['asana_mind_url']) + """;
        window.__user_email = """ + json.dumps(inj_data['user_email']) + """;
        window.__user_name = """ + json.dumps(inj_data['user_name']) + """;
        window.__user_picture = """ + json.dumps(inj_data['user_picture']) + """;
        // CRITICAL — wipe stale local state if it belongs to a different user.
        // Runs BEFORE any application script reads localStorage. This is the
        // only way to guarantee no cross-account state bleed on the same
        // browser, regardless of cache state.
        (function() {
            try {
                const me = (window.__user_email || '').toLowerCase();
                const owner = (localStorage.getItem('sunday_user_email') || '').toLowerCase();
                if (me && owner && me !== owner) {
                    console.log('[boot] account switch:', owner, '\u2192', me, '\u2014 clearing per-user cache');
                    ['courseProgress','sundayCourseStartDate','sunday_voice_history','sunday_pose_difficulty','sunday_onboarding_done'].forEach(k => {
                        try { localStorage.removeItem(k); } catch(_){}
                    });
                }
                if (me) localStorage.setItem('sunday_user_email', me);
            } catch(_) {}
        })();
    </script>
    """
    if '</head>' in content:
        content = content.replace('</head>', f'{injection}</head>')
    else:
        content = injection + content

    # Return as raw response — main.html is a literal HTML file with no
    # Jinja templating, so we skip render_template_string to avoid any
    # accidental processing of user-controlled curly braces.
    response = app.make_response(content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    # Never let any proxy / browser keep this page — it's user-specific HTML.
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/profile')
def profile_page():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    if not os.path.exists('profile.html'):
        return "Error: profile.html not found in app directory. Place it here.", 500
        
    with open('profile.html', 'r', encoding='utf-8') as f:
        content = f.read()

    response = app.make_response(content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# Set ALLOW_LEGACY_LOGIN=1 to keep the old name+email login working.
# By default it's disabled — it's effectively no auth (no password) and
# was only kept around for early test users. Google sign-in is the safe path.
ALLOW_LEGACY_LOGIN = os.environ.get('ALLOW_LEGACY_LOGIN', '').strip() == '1'


@app.route('/register', methods=['POST'])
def register():
    if not ALLOW_LEGACY_LOGIN:
        return jsonify({'success': False, 'error': 'Email registration is disabled. Sign in with Google.'}), 403
    if not db_connected:
        return jsonify({'success': False, 'error': 'Database not available'}), 500
    
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    
    if not name or not email:
        return jsonify({'success': False, 'error': 'Name and email are required'}), 400
    
    existing_user = users.find_one({'email': email})
    if existing_user:
        return jsonify({'success': False, 'error': 'User already registered with this email'}), 400
    
    today = datetime.now().strftime('%Y-%m-%d')
    user_data = {
        'name': name,
        'email': email,
        'created_at': datetime.utcnow(),
        'activity_log': [today],  # Init with today
        'completed_asanas': {}    # Dynamic object for counts
    }
    result = users.insert_one(user_data)
    
    if result.inserted_id:
        session.permanent = True
        session['logged_in'] = True
        session['user_email'] = email
        session['user_name'] = name
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Registration failed'}), 500

@app.route('/login', methods=['POST'])
def login():
    if not ALLOW_LEGACY_LOGIN:
        return jsonify({'success': False, 'error': 'Email login is disabled. Sign in with Google.'}), 403
    if not db_connected:
        return jsonify({'success': False, 'error': 'Database not available'}), 500
    
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    
    if not name or not email:
        return jsonify({'success': False, 'error': 'Name and email are required'}), 400
    
    user = users.find_one({'email': email})
    if not user:
        return jsonify({'success': False, 'error': 'No user found with this email'}), 400
    
    if user['name'] != name:
        return jsonify({'success': False, 'error': 'Name does not match registered user'}), 400
    
    # Add today to activity_log if not exists
    today = datetime.now().strftime('%Y-%m-%d')
    users.update_one({'email': email}, {'$addToSet': {'activity_log': today}})
    
    session.permanent = True
    session['logged_in'] = True
    session['user_email'] = email
    session['user_name'] = name
    return jsonify({'success': True})

@app.route('/auth/google', methods=['POST'])
def google_auth():
    """Sign in / sign up via Google ID token (item: Google Sign-In).

    Frontend calls google.accounts.id.prompt() which returns a JWT ID token.
    We verify the token against Google's public keys, then create or look up
    the user in our DB.
    """
    if not GOOGLE_AUTH_AVAILABLE:
        return jsonify({'success': False, 'error': 'Google sign-in not configured on server.'}), 503
    if not GOOGLE_CLIENT_ID:
        return jsonify({'success': False, 'error': 'GOOGLE_CLIENT_ID env var not set.'}), 503
    if not db_connected:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    data = request.get_json(silent=True) or {}
    token = data.get('credential') or data.get('token')
    if not token:
        return jsonify({'success': False, 'error': 'Missing credential'}), 400

    try:
        # Verify the JWT against Google's certs and our client ID.
        info = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID, clock_skew_in_seconds=10)
    except ValueError as e:
        # Don't leak library internals — just say it failed and log details.
        print(f'Google token verification failed: {e}')
        return jsonify({'success': False, 'error': 'Invalid or expired Google sign-in token. Please try again.'}), 401

    email = (info.get('email') or '').lower().strip()
    if not email or not info.get('email_verified'):
        return jsonify({'success': False, 'error': 'Google account email is not verified.'}), 401

    name = (info.get('name') or info.get('given_name') or email.split('@')[0]).strip()
    picture = info.get('picture', '')
    google_sub = info.get('sub')

    today = datetime.now().strftime('%Y-%m-%d')

    # ── Invitation gate (multi-tenant) ──
    # Check if this Google email is associated with a pending invitation,
    # OR is already an existing user, OR matches the test-org domain
    # wildcard. If none of these, refuse sign-in to keep the app private
    # to invited users only.
    consume_inv = _org_helpers.get('consume_invitation_for') if _org_helpers else None
    invitation = consume_inv(email) if consume_inv else None
    invite_token_in_session = session.get('invite_token')
    if invite_token_in_session and not invitation:
        # User clicked an invite link with a token but the email mismatched.
        # Don't strand them — fall through and let the existing-user path handle it.
        pass

    existing = g_users.find_one({'email': email}) if g_users is not None else None

    # If neither an invitation nor an existing user, AND the test org
    # accepts wildcard domain, we let them in as test-org students. This
    # preserves the "previous users continue working" guarantee.
    if not invitation and not existing:
        # Look up the test org to see if wildcard signups are allowed.
        test_org = None
        if organizations_col is not None:
            test_org = organizations_col.find_one({'email': _org_helpers.get('TEST_ORG_EMAIL', 'test@asanminds.local')})
        if not test_org or test_org.get('domain') != '*':
            return jsonify({
                'success': False,
                'error': 'You need an invitation from your organization to use AsanMinds. Ask your admin to send you a link.',
            }), 403

    # Google users live in the dedicated google_auth DB so they're truly
    # isolated from the legacy face_auth records.
    if existing:
        # Backfill Google linkage and update profile fields from Google's
        # verified data — Google's name and picture always win because they
        # are user-controlled identity (vs whatever was typed in the old
        # name+email flow). Activity log is still appended.
        update = {
            'name': name,
            'picture': picture,
            'google_sub': google_sub,
            'auth_provider': 'google',
        }
        # If they accepted an invitation, refresh their role/org/academic.
        if invitation:
            update['role'] = invitation.get('role') or 'student'
            update['organizationEmail'] = invitation.get('organizationEmail')
            pf = invitation.get('prefilled') or {}
            if pf:
                academic = {k: pf.get(k) for k in ('batch', 'branch', 'section', 'usn', 'rollNumber') if pf.get(k)}
                if 'currentSemester' in pf:
                    academic['currentSemester'] = pf['currentSemester']
                if academic:
                    update['academic'] = academic
                if pf.get('name') and not existing.get('name'):
                    update['name'] = pf['name']
        g_users.update_one(
            {'email': email},
            {'$set': update, '$addToSet': {'activity_log': today}},
        )
        session_name = update.get('name') or name
    else:
        # New user — invitation must exist (we'd have rejected above otherwise).
        new_doc = {
            'name': name,
            'email': email,
            'picture': picture,
            'google_sub': google_sub,
            'auth_provider': 'google',
            'created_at': datetime.utcnow(),
            'activity_log': [today],
            'completed_asanas': {},
        }
        if invitation:
            new_doc['role'] = invitation.get('role') or 'student'
            new_doc['organizationEmail'] = invitation.get('organizationEmail')
            pf = invitation.get('prefilled') or {}
            academic = {k: pf.get(k) for k in ('batch', 'branch', 'section', 'usn', 'rollNumber') if pf.get(k)}
            if 'currentSemester' in pf:
                academic['currentSemester'] = pf['currentSemester']
            if academic:
                new_doc['academic'] = academic
            if pf.get('name'):
                new_doc['name'] = pf['name']
        else:
            # Wildcard test-org sign-up.
            new_doc['role'] = 'student'
            new_doc['organizationEmail'] = _org_helpers.get('TEST_ORG_EMAIL', 'test@asanminds.local')
            new_doc['academic'] = {'batch': 'test', 'branch': 'TEST', 'section': 'T'}
        g_users.insert_one(new_doc)
        session_name = new_doc['name']

        # Send a one-time welcome email to brand-new STUDENT enrollees who
        # signed up via an invitation. We mark `welcomed=True` after sending
        # so a re-login never re-sends the welcome message.
        try:
            send_welcome = _org_helpers.get('send_welcome_email') if _org_helpers else None
            if send_welcome and invitation and (new_doc.get('role') == 'student'):
                org_email_for_welcome = new_doc.get('organizationEmail') or ''
                org_name_for_welcome = 'AsanMinds'
                if organizations_col is not None and org_email_for_welcome:
                    org_doc_lookup = organizations_col.find_one({'email': org_email_for_welcome})
                    if org_doc_lookup and org_doc_lookup.get('name'):
                        org_name_for_welcome = org_doc_lookup['name']
                send_welcome(email, new_doc.get('name') or name, org_name_for_welcome)
                g_users.update_one({'email': email}, {'$set': {'welcomed': True, 'welcomedAt': datetime.utcnow()}})
        except Exception as exc:
            # Welcome email is best-effort; never block sign-in on it.
            print(f'Welcome email dispatch failed for {email}: {exc!r}')

    # Final lookup to capture role/org for the session.
    final = g_users.find_one({'email': email}) or {}

    session.permanent = True
    session.clear()  # remove any stale legacy-flow keys
    session.permanent = True
    session['logged_in'] = True
    session['user_email'] = email
    session['user_name'] = session_name
    session['picture'] = picture
    session['auth_provider'] = 'google'
    session['role'] = final.get('role') or 'student'
    session['organizationEmail'] = final.get('organizationEmail')
    return jsonify({
        'success': True,
        'name': session_name,
        'email': email,
        'picture': picture,
        'role': session['role'],
        'organizationEmail': session.get('organizationEmail'),
    })


@app.route('/auth/google/config', methods=['GET'])
def google_config():
    """Tells the frontend whether Google sign-in is configured and the client ID."""
    return jsonify({
        'enabled': bool(GOOGLE_AUTH_AVAILABLE and GOOGLE_CLIENT_ID),
        'clientId': GOOGLE_CLIENT_ID,
    })


@app.route('/api/profile')
def profile():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401

    email = session.get('user_email')
    if not email:
        return jsonify({'error': 'No email in session'}), 401

    users_col = get_users_col()
    if users_col is None:
        # Fall back to session-only data so the UI still renders something.
        return jsonify({
            'name': session.get('user_name') or 'Practitioner',
            'email': email,
            'picture': session.get('picture', ''),
            'auth_provider': session.get('auth_provider', 'email'),
            'created_at': None,
            'activity_log': [],
            'completed_asanas': {},
            'total_active_days': 0,
        })

    try:
        user = users_col.find_one({'email': email})
    except Exception as e:
        print(f'profile DB error: {e}')
        user = None

    if user:
        activity_log = sorted(user.get('activity_log', []) or [])
        created_at = user.get('created_at')
        return jsonify({
            'name': user.get('name') or session.get('user_name') or 'Practitioner',
            'email': user.get('email') or email,
            'picture': user.get('picture') or session.get('picture', ''),
            'auth_provider': user.get('auth_provider', 'email'),
            'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else (created_at or None),
            'activity_log': activity_log,
            'completed_asanas': user.get('completed_asanas', {}) or {},
            'total_active_days': len(activity_log),
        })

    # User not found in DB — return session info so UI doesn't break.
    return jsonify({
        'name': session.get('user_name') or 'Practitioner',
        'email': email,
        'picture': session.get('picture', ''),
        'auth_provider': session.get('auth_provider', 'email'),
        'created_at': None,
        'activity_log': [],
        'completed_asanas': {},
        'total_active_days': 0,
    })

@app.route('/api/complete_pose', methods=['POST'])
def complete_pose():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    if not db_connected:
        return jsonify({'success': False, 'error': 'Database not available'}), 500
    
    data = request.get_json()
    pose_name = data.get('pose_name')
    accuracy = data.get('accuracy', 0)
    time_held = data.get('time_held', 0)
    
    if time_held < 10:
        return jsonify({'success': True, 'message': 'Pose logged but not counted as successful (under 10s)'})
    
    email = session['user_email']
    today = datetime.now().strftime('%Y-%m-%d')

    # Update: Inc count and add date
    get_users_col().update_one(
        {'email': email},
        {
            '$inc': {f'completed_asanas.{pose_name}': 1},
            '$addToSet': {'activity_log': today}
        }
    )
    return jsonify({'success': True, 'message': f'{pose_name} completed successfully!'})

@app.route('/logout')
def logout():
    session.clear()
    # Hard browser-side cleanup. The Clear-Site-Data header is supported by
    # Chrome / Edge / Firefox and instructs the browser to drop ALL site data
    # (cookies, localStorage, sessionStorage, indexedDB, cache storage, and
    # service-worker registrations). This is the only deterministic way to
    # prevent stale per-user state from leaking into the next account on the
    # same device.
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Signing out…</title></head>
<body style="background:#F5F2EB;font-family:Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;color:#4A453B">
<div style="text-align:center">
  <p style="font-family:Fraunces,serif;font-size:24px;font-weight:300;color:#14120E;margin:0">Signing you out…</p>
  <p style="margin:10px 0 0;color:#7A7364;font-size:13px">Cleaning up your device…</p>
</div>
<script>
(function(){
    try {
        // Belt-and-braces: client-side wipe in case the browser ignores the header.
        const keys = ['courseProgress','sundayCourseStartDate','sunday_voice_history','sunday_pose_difficulty','sunday_onboarding_done','sunday_user_email','sunday_font_size'];
        for (const k of keys) localStorage.removeItem(k);
        try { sessionStorage.clear(); } catch(_){}
        if ('caches' in window) caches.keys().then(ks => ks.forEach(k => caches.delete(k)));
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister()));
        }
    } catch(_){}
    setTimeout(() => window.location.replace('/'), 400);
})();
</script>
</body></html>"""
    response = app.make_response(html)
    response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage", "executionContexts"'
    response.headers['Cache-Control'] = 'no-store'
    return response

# Serve PWA Static Assets (Manifest & Service Worker)
@app.route('/manifest.json')
@app.route('/manifest.webmanifest')
def serve_manifest():
    """Serve the PWA manifest with the correct MIME type.

    Chrome's installability check is strict about Content-Type:
    `application/manifest+json` is preferred over plain
    `application/json`. Render's default static handler returns the
    latter, which has been observed to silently downgrade installs
    to "Add to Home Screen" on some devices.
    """
    resp = send_from_directory('.', 'manifest.json')
    resp.headers['Content-Type'] = 'application/manifest+json; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp


@app.route('/sw.js')
def serve_sw():
    """Serve the service worker with Service-Worker-Allowed for full scope."""
    resp = send_from_directory('.', 'sw.js')
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp

# Serve static assets
@app.route('/assets/<path:filename>')
def serve_asset(filename):
    try:
        return send_from_directory('assets', filename)
    except FileNotFoundError:
        return "Asset not found.", 404


# PWA install diagnostic — visit /install-debug on your phone to see
# exactly what Chrome thinks of the install eligibility. Useful when
# the install banner refuses to appear.
@app.route('/install-debug')
def install_debug():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PWA install diagnostic · AsanMinds</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0F3D2E">
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#F5F2EB;color:#14120E;margin:0;padding:24px;line-height:1.55;max-width:680px;margin:0 auto}
h1{font-size:22px;margin:0 0 8px;color:#0F3D2E}
.card{background:#fff;border:1px solid #D4CCB8;border-radius:14px;padding:16px;margin:12px 0}
.ok{color:#3E8A52;font-weight:600}
.bad{color:#C2552F;font-weight:600}
.warn{color:#A16207;font-weight:600}
code{background:#EEE9DE;padding:2px 6px;border-radius:4px;font-size:12px;font-family:ui-monospace,monospace}
pre{background:#EEE9DE;padding:12px;border-radius:8px;font-size:11px;overflow-x:auto;line-height:1.5}
button{background:#0F3D2E;color:#F5F2EB;border:0;padding:14px 24px;border-radius:9999px;font-size:14px;font-weight:600;cursor:pointer;margin-top:8px;width:100%;font-family:inherit}
button:disabled{background:#A8A294;cursor:not-allowed}
.row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #EEE9DE}
.row:last-child{border-bottom:0}
.label{color:#7A7364;font-size:13px}
</style>
</head><body>
<h1>PWA install diagnostic</h1>
<p style="color:#7A7364;font-size:13px;margin:4px 0 18px">If install isn't working on this device, this page tells you why.</p>

<div class="card">
  <h3 style="margin:0 0 10px;font-size:15px">Chrome's install criteria</h3>
  <div id="criteria">Loading...</div>
</div>

<div class="card">
  <h3 style="margin:0 0 10px;font-size:15px">Try the install prompt</h3>
  <p id="prompt-status" style="font-size:13px;color:#7A7364;margin:0 0 8px">Waiting for the browser to fire <code>beforeinstallprompt</code>...</p>
  <button id="prompt-btn" disabled>Install now</button>
</div>

<div class="card">
  <h3 style="margin:0 0 10px;font-size:15px">Manifest snapshot</h3>
  <pre id="manifest">Loading...</pre>
</div>

<div class="card">
  <h3 style="margin:0 0 10px;font-size:15px">Service worker</h3>
  <div id="sw">Loading...</div>
</div>

<script>
(async function(){
  const out = document.getElementById('criteria');
  const rows = [];
  function row(label, val, kind){
    const cls = kind === 'ok' ? 'ok' : kind === 'bad' ? 'bad' : 'warn';
    rows.push(`<div class="row"><span class="label">${label}</span><span class="${cls}">${val}</span></div>`);
  }

  row('HTTPS', location.protocol === 'https:' ? 'yes' : 'NO (required)', location.protocol === 'https:' ? 'ok' : 'bad');

  // Manifest fetch
  let manifestOk = false;
  let manifestData = null;
  try {
    const r = await fetch('/manifest.json');
    if (r.ok) {
      manifestData = await r.json();
      manifestOk = true;
      row('Manifest reachable', `200, type=${r.headers.get('content-type')||'?'}`, 'ok');
    } else {
      row('Manifest reachable', `${r.status}`, 'bad');
    }
  } catch(e) {
    row('Manifest reachable', 'fetch failed', 'bad');
  }
  document.getElementById('manifest').textContent = manifestData ? JSON.stringify(manifestData, null, 2) : 'Could not load.';

  if (manifestData) {
    row('manifest.name', manifestData.name || manifestData.short_name || 'MISSING', (manifestData.name || manifestData.short_name) ? 'ok' : 'bad');
    row('manifest.start_url', manifestData.start_url || 'MISSING', manifestData.start_url ? 'ok' : 'bad');
    row('manifest.display', manifestData.display, ['standalone','fullscreen','minimal-ui'].includes(manifestData.display) ? 'ok' : 'bad');
    const icons = manifestData.icons || [];
    const has192 = icons.some(i => (i.sizes||'').includes('192'));
    const has512 = icons.some(i => (i.sizes||'').includes('512'));
    const hasMaskable = icons.some(i => (i.purpose||'').includes('maskable'));
    row('icon 192x192', has192 ? 'yes' : 'NO (required)', has192 ? 'ok' : 'bad');
    row('icon 512x512', has512 ? 'yes' : 'NO (required)', has512 ? 'ok' : 'bad');
    row('maskable icon', hasMaskable ? 'yes' : 'no (recommended)', hasMaskable ? 'ok' : 'warn');
  }

  // Test start_url cold
  if (manifestData && manifestData.start_url) {
    try {
      const r = await fetch(manifestData.start_url, { credentials: 'omit', redirect: 'manual' });
      const isOk = r.type === 'opaqueredirect' ? false : r.ok;
      const code = r.type === 'opaqueredirect' ? '302 redirect' : r.status;
      row('start_url returns 200 cold', `${code}`, isOk ? 'ok' : 'bad');
    } catch(e) {
      row('start_url returns 200 cold', 'fetch error', 'bad');
    }
  }

  // SW
  if ('serviceWorker' in navigator) {
    const reg = await navigator.serviceWorker.getRegistration();
    row('Service worker registered', reg ? 'yes' : 'NO (required)', reg ? 'ok' : 'bad');
    document.getElementById('sw').innerHTML = reg
      ? `<p style="font-size:13px;margin:0">Active: <code>${reg.active ? reg.active.scriptURL : 'pending'}</code></p>
         <p style="font-size:13px;margin:6px 0 0">Scope: <code>${reg.scope}</code></p>`
      : '<p class="bad">Not registered. The install prompt requires an active service worker.</p>';
  } else {
    row('Service worker support', 'no', 'bad');
    document.getElementById('sw').textContent = 'This browser has no service worker support.';
  }

  // Display mode
  if (window.matchMedia('(display-mode: standalone)').matches) {
    row('Already installed', 'yes (running as PWA)', 'ok');
  } else {
    row('Already installed', 'no', 'warn');
  }

  out.innerHTML = rows.join('');
})();

let deferred = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferred = e;
  document.getElementById('prompt-btn').disabled = false;
  document.getElementById('prompt-status').innerHTML =
    '<span class="ok">Browser fired <code>beforeinstallprompt</code> — install is supported on this device.</span>';
});
window.addEventListener('appinstalled', () => {
  document.getElementById('prompt-status').innerHTML =
    '<span class="ok">Installed. Check your launcher.</span>';
});
document.getElementById('prompt-btn').onclick = async () => {
  if (!deferred) return;
  deferred.prompt();
  const choice = await deferred.userChoice;
  document.getElementById('prompt-status').innerHTML =
    `<span class="ok">User choice: ${choice.outcome}</span>`;
  deferred = null;
  document.getElementById('prompt-btn').disabled = true;
};

// SW
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
</script>
</body></html>"""


# =============================================================
# AI Assistant proxy — keeps API key on the server, avoids
# browser CORS, falls back to offline yoga tips when the
# upstream AI is unreachable.
# =============================================================

# ─────────────────────────────────────────────────────────────
# App Knowledge Base — everything Sunday knows about itself.
# This is the ground truth the AI reads (via the system prompt)
# AND the offline fallback searches (when no API key is set).
# Keep pose summaries in sync with static/poses.js.
# ─────────────────────────────────────────────────────────────

APP_KB = {
    'identity': (
        'Sunday is the calm voice of AsanaMind, a browser-based yoga practice app. '
        'It uses your phone or laptop camera with Google\u2019s MoveNet Thunder pose model '
        'to score alignment in real time, read corrections aloud, and walk you through '
        'a twenty-pose certificate course.'
    ),
    'stack': (
        'Front-end runs TensorFlow.js MoveNet SinglePose Thunder at ~30 fps with per-keypoint EMA '
        'smoothing, a rule hysteresis filter (7-frame fail / 5-frame pass), stance-aware rules '
        'for asymmetric poses like Warrior and Triangle, and a template-matching scorer based on '
        'joint-angle deviation (Borthakur 2023, Anjali 2025). Flask on the back end, MongoDB '
        'for progress, deployed on Render.'
    ),
    'course': (
        'The course holds the same twenty poses as the library. Hold each pose at ninety percent '
        'alignment for ten continuous seconds to pass. You get three attempts per pose. Finish all '
        'twenty and you earn a certificate on your profile page.'
    ),
    'library': (
        'The library has twenty curated MoveNet-friendly poses: ten Beginner, seven Intermediate, '
        'three Advanced. Inversions are excluded because the model cannot score them fairly.'
    ),
    'practice': (
        'Practice uses your camera and MoveNet Thunder. Green skeleton means confident detection. '
        'A rule must fail for seven frames before it becomes a spoken correction, and pass for five '
        'to clear, so you don\u2019t get chatter. The score uses both rule-based corrections and a '
        'continuous template-matching score from joint-angle deviation.'
    ),
    'profile': (
        'Your profile shows total sessions, active days, best streak, poses learned, an eight-week '
        'minutes chart, pose distribution, a one-year rhythm heatmap, and up to eight achievement badges.'
    ),
    'levels': (
        'Level progression runs: Novice at one day, Novice II at one, Regular I at seven, Regular II '
        'at fourteen, Expert I at thirty, Expert II at sixty, Master at one-hundred-and-twenty active days.'
    ),
    'privacy': (
        'Pose detection runs entirely in your browser. No video is ever sent to the server. Only '
        'completion counts and activity dates are stored in MongoDB.'
    ),
    'research': (
        'The pose scoring draws on three papers: Google\u2019s MoveNet 2021 for the detector, '
        'Borthakur 2023 in MDPI Healthcare for angle-feature-based pose quality, and Anjali 2025 '
        'in IJRASET for MoveNet Thunder with a template-matching scorer.'
    ),
    'breathing': (
        'Two breaths we use: Ujjayi for practice (inhale and exhale through the nose with a soft '
        'throat constriction), and four-four-four-four box breath for calm (say \u201cbreathe with me\u201d).'
    ),
    'meditation': 'Sit tall in Sukhasana, close the eyes, let the breath be slow and even. Start with three minutes and build up.',
    'stress': 'For stress, move slowly through Child\u2019s Pose, Seated Forward Fold, and long exhales. Let the body soften.',
    'back pain': 'For back relief, try Bridge Pose, Cat\u2013Cow, gentle twists, and Legs Up the Wall. Move gently, never force.',
    'beginner start': 'Start with Tadasana, Anjali Mudra, Vrikshasana, and Balasana for the first week. Short and steady builds a practice.',
}

# Short, voice-ready pose summaries. Keys are lowercase so keyword lookup is trivial.
POSE_KB = {
    'tadasana': 'Tadasana, Mountain Pose, beginner, front view. Stand with feet hip-width, weight even, crown lifting. Foundation of every standing asana.',
    'urdhva hastasana': 'Urdhva Hastasana, Upward Salute, beginner. Stand tall and reach both arms overhead. Opens the chest and resets breathing.',
    'anjali mudra': 'Anjali Mudra, Prayer at Heart, beginner. Palms together at the heart. A centering gesture that quiets the mind.',
    'vrikshasana': 'Vrikshasana, Tree Pose, beginner. Root the standing foot; place the raised sole on the inner calf or thigh. Trains balance and focus.',
    'uttanasana': 'Uttanasana, Standing Forward Fold, beginner, side view. Hinge at the hips, soften the knees, let the head hang. Lengthens the back body.',
    'sukhasana': 'Sukhasana, Easy Seated Pose, beginner. Sit crossed-legged on a cushion, spine tall. Foundation for breathwork and meditation.',
    'dandasana': 'Dandasana, Staff Pose, beginner, side view. Sit with legs extended and spine tall. The seated equivalent of Tadasana.',
    'baddha konasana': 'Baddha Konasana, Bound Angle, beginner. Sit, soles together, knees wide. Opens inner thighs and hips.',
    'paschimottanasana': 'Paschimottanasana, Seated Forward Fold, beginner, side view. Fold over extended legs. Stretches the whole back line.',
    'balasana': 'Balasana, Child\u2019s Pose, beginner, side view. Knees wide, hips to heels, forehead down. A resting pose between stronger asanas.',
    'adho mukha svanasana': 'Adho Mukha Svanasana, Downward-Facing Dog, intermediate, side view. Hips high, arms straight, heels reach down. Full-body tonic.',
    'virabhadrasana i': 'Virabhadrasana I, Warrior I, intermediate, side view. Front knee bent, back leg straight, arms overhead. Strengthens legs and opens hip flexors.',
    'virabhadrasana ii': 'Virabhadrasana II, Warrior II, intermediate, front view. Front knee over ankle, arms parallel to the floor, gaze over the front hand.',
    'utthita trikonasana': 'Utthita Trikonasana, Extended Triangle, intermediate, side view. Front leg straight, torso reaches long, bottom hand to shin or block.',
    'utkatasana': 'Utkatasana, Chair Pose, intermediate, side view. Knees bent as if sitting in a chair, arms overhead. Builds heat and strength.',
    'utthita parsvakonasana': 'Utthita Parsvakonasana, Extended Side Angle, intermediate, side view. Front knee bent, top arm reaches over the ear, bottom hand to floor or block.',
    'setu bandhasana': 'Setu Bandhasana, Bridge Pose, intermediate, side view. On your back, feet hip-width, lift the hips. Opens chest and hip flexors.',
    'virabhadrasana iii': 'Virabhadrasana III, Warrior III, advanced, side view. Balance on one leg, torso and back leg parallel to the floor, arms forward.',
    'ardha chandrasana': 'Ardha Chandrasana, Half Moon, advanced, side view. Balance on one hand and one foot, top leg and arm reach long.',
    'natarajasana': 'Natarajasana, Dancer, advanced, side view. Stand on one leg, catch the back foot, arc the chest forward. Elegant backbend and balance.',
}

# Pose aliases people actually say — maps loose phrases to POSE_KB keys.
POSE_ALIASES = {
    'mountain': 'tadasana', 'mountain pose': 'tadasana',
    'tree': 'vrikshasana', 'tree pose': 'vrikshasana',
    'prayer': 'anjali mudra', 'namaste': 'anjali mudra',
    'down dog': 'adho mukha svanasana', 'downward dog': 'adho mukha svanasana', 'downward-facing dog': 'adho mukha svanasana',
    'warrior one': 'virabhadrasana i', 'warrior 1': 'virabhadrasana i',
    'warrior two': 'virabhadrasana ii', 'warrior 2': 'virabhadrasana ii',
    'warrior three': 'virabhadrasana iii', 'warrior 3': 'virabhadrasana iii',
    'triangle': 'utthita trikonasana', 'extended triangle': 'utthita trikonasana',
    'chair': 'utkatasana', 'chair pose': 'utkatasana',
    'side angle': 'utthita parsvakonasana', 'extended side angle': 'utthita parsvakonasana',
    'bridge': 'setu bandhasana', 'bridge pose': 'setu bandhasana',
    'half moon': 'ardha chandrasana', 'dancer': 'natarajasana', 'dancer pose': 'natarajasana',
    'child': 'balasana', 'child pose': 'balasana', 'childs pose': 'balasana',
    'easy': 'sukhasana', 'easy seat': 'sukhasana', 'easy pose': 'sukhasana',
    'staff': 'dandasana', 'staff pose': 'dandasana',
    'bound angle': 'baddha konasana', 'butterfly': 'baddha konasana',
    'forward fold': 'paschimottanasana', 'seated forward fold': 'paschimottanasana',
    'standing forward fold': 'uttanasana', 'rag doll': 'uttanasana',
    'upward salute': 'urdhva hastasana', 'reach up': 'urdhva hastasana',
}

# Screen-aware fallbacks for "what is this / where am I" questions.
SCREEN_FALLBACKS = {
    'Home / Today': 'You\u2019re on the home screen. Start today\u2019s practice, browse the library, open the course, or say "my stats".',
    'Asana library': 'You\u2019re in the asana library. Pick any of the twenty poses to start practising, or say the name of a pose.',
    'AR practice session': 'You\u2019re in the practice screen. Your camera scores alignment against the reference in real time. Say "score", "reference", "next", or "stop".',
    'Certificate course': 'You\u2019re in the course. Hold each pose at ninety percent for ten seconds, three attempts, twenty poses, one certificate.',
    'AI assistant': 'You\u2019re with me, Sunday. Ask anything about yoga, your practice, or the app. Say "commands" to see what I can do.',
    'Profile': 'You\u2019re on your profile. It tracks sessions, active days, best streak, pose distribution, a year-long rhythm heatmap, and badges.',
}

def _kb_search(query: str):
    """Lightweight keyword scorer. Returns the best-matching KB snippet or None."""
    q = (query or '').lower()
    # Pose aliases first — "tell me about warrior two" should hit the pose entry.
    for alias, key in POSE_ALIASES.items():
        if alias in q and key in POSE_KB:
            return POSE_KB[key]
    for key, text in POSE_KB.items():
        if key in q:
            return text

    # App-level KB — tokenise both the key and a curated set of terms per entry.
    # We use the entry value itself as extra search text so "how does the scoring
    # work" hits the `practice` entry via the word "score".
    KB_TERMS = {
        'identity': ['sunday', 'asanamind', 'app', 'what is sunday', 'who are you'],
        'stack': ['stack', 'movenet', 'tensorflow', 'thunder', 'model', 'how does it work', 'technology', 'tech'],
        'course': ['course', 'test', 'certificate exam', 'passing', 'ninety percent', 'ten seconds'],
        'library': ['library', 'poses list', 'how many poses', 'beginner', 'intermediate', 'advanced'],
        'practice': ['practice', 'score', 'scoring', 'alignment', 'correction', 'real time', 'ar', 'camera', 'rule', 'hysteresis', 'smoothing'],
        'profile': ['profile', 'dashboard', 'kpi', 'streak', 'badges', 'heatmap', 'sessions'],
        'levels': ['level', 'levels', 'progression', 'rank', 'novice', 'expert', 'master', 'regular'],
        'privacy': ['privacy', 'data', 'personal', 'recorded', 'stored', 'video', 'secure'],
        'research': ['research', 'paper', 'borthakur', 'anjali', 'mdpi', 'ijraset', 'citation', 'study'],
        'breathing': ['breathing', 'breath', 'ujjayi', 'pranayama', 'box breath'],
        'meditation': ['meditation', 'meditate', 'quiet mind', 'stillness'],
        'stress': ['stress', 'anxious', 'anxiety', 'overwhelmed'],
        'back pain': ['back pain', 'sore back', 'lower back', 'spine hurts'],
        'beginner start': ['where do i start', 'new here', 'first week', 'beginner routine', 'how to start'],
    }
    best = (0, None)
    for key, text in APP_KB.items():
        terms = KB_TERMS.get(key, [key])
        score = 0
        for term in terms:
            if term in q:
                score += 2 if ' ' in term else 1
        if score > best[0]:
            best = (score, text)
    return best[1] if best[0] > 0 else None

def yoga_fallback(prompt: str, ctx: dict = None) -> str:
    """Offline, no-API-key fallback that stays useful by searching the knowledge base."""
    p = (prompt or '').lower()
    ctx = ctx or {}

    # Commands question — list what Sunday can do.
    if any(phrase in p for phrase in ('commands', 'what can you do', 'what can i say', 'help me', 'list commands', 'command list')):
        return ('I can start poses, score alignment, show reference, cycle next and previous, read the screen, speak your stats, '
                'recommend a pose, run box-breath, toggle diagnostics, open the course, and answer yoga questions. '
                'Tap the question-mark in the top bar for the full command library.')

    # "what is this / where am i" → describe the current screen.
    if any(phrase in p for phrase in ('what is this', 'what\u2019s this', 'whats this', 'where am i', 'what am i looking at', 'what page', 'what screen')):
        screen = ctx.get('screen')
        if screen and screen in SCREEN_FALLBACKS:
            return SCREEN_FALLBACKS[screen]
        if ctx.get('poseSanskrit'):
            return f"You\u2019re practising {ctx['poseSanskrit']}. Say \u201cscore\u201d for alignment or \u201creference\u201d to see the pose."

    # "about this pose" while a pose is selected.
    if ('this pose' in p or 'about this' in p or 'tell me more' in p) and ctx.get('pose'):
        key = ctx['pose'].lower()
        if key in POSE_KB:
            return POSE_KB[key]

    # Knowledge-base keyword search
    hit = _kb_search(p)
    if hit:
        return hit

    return 'I\u2019m Sunday, your yoga coach. Ask me about a pose, the course, breathing, or say \u201ccommands\u201d to see what I can do.'


@app.route('/api/assistant', methods=['POST'])
@rate_limit_assistant
def assistant_proxy():
    """Server-side proxy for the AI assistant. Rate-limited to 30 calls/minute
    per IP (when flask-limiter is available)."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    # Cap prompt length to prevent quota burns and DoS.
    if len(prompt) > 2000:
        prompt = prompt[:2000]
    if not prompt:
        return jsonify({'success': False, 'error': 'Empty prompt'}), 400
    ctx = data.get('context') or {}

    api_key = os.environ.get('OPENROUTER_API_KEY') or os.environ.get('GEMINI_API_KEY') or ''
    # Fallback path — no key set or upstream unreachable.
    if not api_key:
        return jsonify({'success': True, 'source': 'fallback', 'text': yoga_fallback(prompt, ctx)})

    # Build a compact context line the model can reason over. We keep it
    # short (models do better with tight system prompts) and strip any
    # fields the client did not send.
    # Cap each context value defensively to prevent prompt-injection /
    # token-burning via fields like a 50KB poseSanskrit string.
    def _cap(v, n=120):
        return str(v or '')[:n]

    ctx_bits = []
    if ctx.get('screen'):
        ctx_bits.append(f"Screen: {_cap(ctx['screen'], 40)}")
    if ctx.get('pose'):
        pose_bit = _cap(ctx['pose'], 60)
        if ctx.get('poseSanskrit') and ctx['poseSanskrit'] != pose_bit:
            pose_bit = f"{pose_bit} ({_cap(ctx['poseSanskrit'], 60)})"
        if ctx.get('poseLevel'):
            pose_bit += f", {_cap(ctx['poseLevel'], 30)}"
        ctx_bits.append(f"Current pose: {pose_bit}")
    if ctx.get('score') is not None:
        try:
            ctx_bits.append(f"Alignment: {int(ctx['score'])}%")
        except Exception:
            pass
    if ctx.get('courseMode'):
        ctx_bits.append("In course test mode")
    if ctx.get('courseCompleted') is not None and ctx.get('courseTotal'):
        try:
            ctx_bits.append(f"Course progress: {int(ctx['courseCompleted'])} of {int(ctx['courseTotal'])} complete")
        except Exception:
            pass
    ctx_line = " | ".join(ctx_bits) if ctx_bits else "No screen context"

    # Compact knowledge base — about 700 tokens. Small enough to include
    # in every request, large enough to make Sunday genuinely informed.
    kb_line = (
        "APP: " + APP_KB['identity'] + " STACK: " + APP_KB['stack'] + " "
        "COURSE: " + APP_KB['course'] + " LIBRARY: " + APP_KB['library'] + " "
        "PRACTICE: " + APP_KB['practice'] + " PROFILE: " + APP_KB['profile'] + " "
        "LEVELS: " + APP_KB['levels'] + " PRIVACY: " + APP_KB['privacy'] + " "
        "RESEARCH: " + APP_KB['research'] + " BREATHING: " + APP_KB['breathing']
    )

    system_msg = (
        "You are Sunday, the calm voice of the AsanaMind yoga app. "
        "Answer in 1 to 3 short sentences, warm and editorial, in a Sunday-morning cadence. "
        "Use the APP context below as ground truth. If the user asks 'what is this', 'where am I', "
        "'what can you do', explain from the context. For pose questions, include the Sanskrit name "
        "and one key cue. Never invent features. Decline medical advice gently and suggest a teacher "
        "or clinician. If the user sounds anxious or in pain, acknowledge it, keep your reply short.\n"
        f"CONTEXT: {ctx_line}\n"
        f"KNOWLEDGE: {kb_line}"
    )
    body = {
        'model': 'google/gemini-2.0-flash-001',
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user', 'content': prompt},
        ],
        'max_tokens': 220,
        'temperature': 0.6,
    }
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': request.url_root.rstrip('/'),
            'X-Title': 'Sunday AsanaMind',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)
        text = (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        if not text:
            return jsonify({'success': True, 'source': 'fallback', 'text': yoga_fallback(prompt, ctx)})
        return jsonify({'success': True, 'source': 'ai', 'text': text})
    except urllib.error.HTTPError as e:
        print(f'AI upstream HTTP {e.code}: {e.reason}')
        return jsonify({'success': True, 'source': 'fallback', 'text': yoga_fallback(prompt, ctx)})
    except Exception as e:
        print(f'AI upstream error: {e}')
        return jsonify({'success': True, 'source': 'fallback', 'text': yoga_fallback(prompt, ctx)})


# ─────────────────────────────────────────────────────────────
# Command registry — the single source of truth for what Sunday
# can do. Used by the command-library modal in the UI and can
# also be recited by the assistant when asked "what can you do".
# ─────────────────────────────────────────────────────────────

COMMANDS = [
    # ── Practice session ─────────────────────────────────────
    {'id': 'start_pose', 'category': 'Practice', 'phrases': ['start tree pose', 'do warrior two', 'open downward dog'],
     'description': 'Start any of the 20 poses by English name, Sanskrit name, or alias.', 'example': 'start tree pose'},
    {'id': 'reference', 'category': 'Practice', 'phrases': ['reference', 'show reference', 'show pose', 'show me', 'picture', 'photo'],
     'description': 'Show the pose reference photo as a full-screen overlay for 5 seconds.', 'example': 'show reference'},
    {'id': 'score', 'category': 'Practice', 'phrases': ['score', 'accuracy', 'how am i doing', 'status'],
     'description': 'Speak your current alignment percentage, with a short coaching note.', 'example': 'score'},
    {'id': 'next', 'category': 'Practice', 'phrases': ['next', 'next pose', 'after this', 'skip'],
     'description': 'Cycle to the next pose in the library.', 'example': 'next pose'},
    {'id': 'previous', 'category': 'Practice', 'phrases': ['previous', 'back pose', 'go back', 'last one'],
     'description': 'Cycle to the previous pose in the library.', 'example': 'previous'},
    {'id': 'stop', 'category': 'Practice', 'phrases': ['stop', 'end', 'quit', 'exit', 'finish', 'done'],
     'description': 'End the current AR practice session.', 'example': 'stop'},
    {'id': 'repeat', 'category': 'Practice', 'phrases': ['repeat', 'again', 'say again', 'one more time'],
     'description': 'Replay the last spoken correction or cue.', 'example': 'again'},
    {'id': 'diagnostics', 'category': 'Practice', 'phrases': ['diagnostics', 'show rules', 'debug', 'details'],
     'description': 'Toggle the per-rule pass/fail panel for developers and the curious.', 'example': 'diagnostics'},
    {'id': 'recommend', 'category': 'Practice', 'phrases': ['recommend', 'suggest', 'what should i do', 'pick for me', 'random pose'],
     'description': 'Pick an appropriate pose for the time of day and start it.', 'example': 'what should I do'},
    {'id': 'timed_hold', 'category': 'Practice', 'phrases': ['hold for 30 seconds', 'timer', 'timed hold', 'start timer', 'count down', 'time me'],
     'description': 'Start a spoken countdown timer. Default 30 seconds. Say "hold for 60 seconds" for custom duration.', 'example': 'hold for 30 seconds'},
    {'id': 'breath_pacing', 'category': 'Practice', 'phrases': ['breath pacing', 'pace my breath', 'breath circle', 'breathing circle'],
     'description': 'Toggle an animated inhale/exhale circle overlay (4 seconds in, 4 seconds out).', 'example': 'breath pacing'},

    # ── Voice + TTS ──────────────────────────────────────────
    {'id': 'voice_guide_on', 'category': 'Voice', 'phrases': ['voice guide on', 'talk to me', 'start voice', 'enable voice', 'speak to me'],
     'description': 'Turn on spoken corrections during practice.', 'example': 'voice guide on'},
    {'id': 'voice_guide_off', 'category': 'Voice', 'phrases': ['voice guide off', 'be quiet', 'stop talking', 'silent mode'],
     'description': 'Turn off spoken corrections, keep visual feedback.', 'example': 'be quiet'},
    {'id': 'voice_off', 'category': 'Voice', 'phrases': ['voice off', 'stop listening', 'turn off', 'mute', 'pause voice'],
     'description': 'Turn the microphone off until you re-enable it.', 'example': 'voice off'},

    # ── Screen / narration ───────────────────────────────────
    {'id': 'read_screen', 'category': 'Screen', 'phrases': ['read this screen', 'what is on screen', 'describe this page', 'read it to me'],
     'description': 'Narrate what\u2019s on the current screen.', 'example': 'read this screen'},
    {'id': 'commands', 'category': 'Screen', 'phrases': ['commands', 'what can you do', 'what can i say', 'list commands', 'command library'],
     'description': 'Open the command library modal with every command grouped and searchable.', 'example': 'commands'},

    # ── Navigation ───────────────────────────────────────────
    {'id': 'nav_home', 'category': 'Navigation', 'phrases': ['go to home', 'open home', 'take me home', 'today'],
     'description': 'Open the Today / home screen.', 'example': 'go to home'},
    {'id': 'nav_library', 'category': 'Navigation', 'phrases': ['go to library', 'open library', 'show library'],
     'description': 'Open the asana library.', 'example': 'open library'},
    {'id': 'nav_practice', 'category': 'Navigation', 'phrases': ['go to practice', 'open practice', 'start practice', 'open camera'],
     'description': 'Open the AR practice screen.', 'example': 'start practice'},
    {'id': 'nav_course', 'category': 'Navigation', 'phrases': ['start the course', 'open the course', 'test me', 'begin test'],
     'description': 'Open the certificate course.', 'example': 'start the course'},
    {'id': 'nav_profile', 'category': 'Navigation', 'phrases': ['profile', 'my profile', 'open profile', 'show profile'],
     'description': 'Open your profile page.', 'example': 'my profile'},
    {'id': 'logout', 'category': 'Navigation', 'phrases': ['logout', 'log out', 'sign out'],
     'description': 'Sign out of Sunday.', 'example': 'sign out'},

    # ── Your data ────────────────────────────────────────────
    {'id': 'my_stats', 'category': 'Data', 'phrases': ['my stats', 'progress', 'streak', 'how many sessions', 'how many days'],
     'description': 'Speak your sessions, active days, streak, and poses learned.', 'example': 'my stats'},
    {'id': 'level', 'category': 'Data', 'phrases': ['level', 'what level', 'current level'],
     'description': 'Speak your current level and what\u2019s next.', 'example': 'what level am I'},
    {'id': 'certificate', 'category': 'Data', 'phrases': ['certificate', 'my certificate', 'show certificate'],
     'description': 'Explain the certificate and open the course.', 'example': 'my certificate'},

    # ── Wellness ─────────────────────────────────────────────
    {'id': 'breathe', 'category': 'Wellness', 'phrases': ['breathe with me', 'calm me', 'anxious', 'anxiety', 'relax', 'breathing'],
     'description': 'Guide you through three rounds of four-four-four-four box breathing.', 'example': 'breathe with me'},

    # ── Ask anything ─────────────────────────────────────────
    {'id': 'ask_ai', 'category': 'Ask Sunday', 'phrases': ['what is this', 'why does', 'how do i', 'tell me about', 'explain', 'which pose for', 'how to fix'],
     'description': 'Any question starting with what / why / how / explain / tell me routes to the AI with full app context and pose-library knowledge.', 'example': 'what is this course?'},
    # ── Accessibility ────────────────────────────────────────
    {'id': 'font_size', 'category': 'Accessibility', 'phrases': ['bigger text', 'larger text', 'smaller text', 'text size', 'font size'],
     'description': 'Cycle through text sizes (16px → 18px → 20px → 22px). Persists across sessions.', 'example': 'bigger text'},
    {'id': 'high_contrast', 'category': 'Accessibility', 'phrases': ['high contrast', 'contrast mode', 'dark mode', 'colourblind', 'accessibility'],
     'description': 'Toggle high-contrast dark mode for low-vision users or bright sunlight.', 'example': 'high contrast'},
]


@app.route('/api/commands', methods=['GET'])
def commands_endpoint():
    """Returns the full command registry. Used by the command-library
    modal in the UI. No auth required so it can be pre-loaded."""
    return jsonify({'success': True, 'commands': COMMANDS})


@app.route('/api/sync-history', methods=['POST'])
def sync_history():
    """Persist localStorage session history to MongoDB (item 37).
    Called periodically by the client so history survives browser clears.
    Accepts { sessions: [...] } and upserts into the user's document."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not db_connected:
        return jsonify({'success': True, 'synced': 0, 'note': 'DB offline'})
    data = request.get_json(silent=True) or {}
    sessions = data.get('sessions') or []
    if not sessions:
        return jsonify({'success': True, 'synced': 0})
    # Sanitise — keep only allowed keys, cap each value, take latest 60.
    allowed_keys = {'pose', 'poseSanskrit', 'peakScore', 'durationS', 'ts'}
    cleaned = []
    for s in sessions[-60:]:
        if not isinstance(s, dict):
            continue
        out = {}
        for k in allowed_keys:
            v = s.get(k)
            if isinstance(v, str):
                out[k] = v[:80]
            elif isinstance(v, (int, float, bool)):
                out[k] = v
            elif v is None:
                continue
        cleaned.append(out)
    if not cleaned:
        return jsonify({'success': True, 'synced': 0})
    email = session.get('user_email', '')
    try:
        get_users_col().update_one(
            {'email': email},
            {'$push': {'session_history': {'$each': cleaned, '$slice': -200}}},
            upsert=True
        )
        return jsonify({'success': True, 'synced': len(cleaned)})
    except Exception as e:
        print(f'sync-history error: {e}')
        return jsonify({'success': True, 'synced': 0, 'note': 'DB error'})


# ─────────────────────────────────────────────────────────────
# COURSE PROGRESS — server-synced (item 1)
# ─────────────────────────────────────────────────────────────

@app.route('/api/course-progress', methods=['GET'])
def get_course_progress():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    col = get_course_progress_col()
    if not db_connected or col is None:
        return jsonify({'success': True, 'progress': None, 'note': 'DB offline'})
    email = session.get('user_email')
    doc = col.find_one({'email': email})
    if not doc:
        return jsonify({'success': True, 'progress': None})
    doc.pop('_id', None)
    return jsonify({'success': True, 'progress': doc.get('progress'), 'updatedAt': doc.get('updatedAt')})


@app.route('/api/course-progress', methods=['PUT', 'POST'])
def save_course_progress():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    col = get_course_progress_col()
    if not db_connected or col is None:
        return jsonify({'success': True, 'note': 'DB offline'})
    data = request.get_json(silent=True) or {}
    progress = data.get('progress')
    if not progress:
        return jsonify({'success': False, 'error': 'Empty progress'}), 400
    email = session.get('user_email')
    col.update_one(
        {'email': email},
        {'$set': {'progress': progress, 'updatedAt': datetime.utcnow().isoformat()}},
        upsert=True,
    )
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────────
# STREAK + STREAK FREEZE (item 5)
# Each user gets 1 streak freeze per ISO week. Auto-applied if a user misses
# a day. Manual trigger via POST /api/streak/freeze (consumes the week token).
# ─────────────────────────────────────────────────────────────

def _iso_week_key(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _ensure_streak_freezes_doc(email):
    col = get_streak_freeze_col()
    if col is None:
        return None
    doc = col.find_one({'email': email})
    if not doc:
        doc = {'email': email, 'usedWeeks': [], 'autoApplied': []}
        col.insert_one(doc)
    return doc


@app.route('/api/streak', methods=['GET'])
def get_streak():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not db_connected:
        return jsonify({'success': True, 'streak': 0, 'best': 0, 'freezeAvailable': False})
    email = session.get('user_email')
    users_col = get_users_col()
    streak_col = get_streak_freeze_col()
    user = users_col.find_one({'email': email})
    activity = sorted(user.get('activity_log', [])) if user else []

    # Compute streak — number of consecutive days up to today, with freeze tokens
    # auto-applied to bridge a single missed day per ISO week.
    today = datetime.utcnow().date()
    freeze_doc = _ensure_streak_freezes_doc(email) if streak_col is not None else None
    auto_applied = list((freeze_doc or {}).get('autoApplied', []))
    used_weeks = set((freeze_doc or {}).get('usedWeeks', []))
    activity_set = set(activity)

    streak = 0
    cursor = today
    while True:
        key = cursor.isoformat()
        if key in activity_set or key in auto_applied:
            streak += 1
            cursor = cursor - timedelta(days=1)
            continue
        # See if a freeze can bridge this missed day.
        wk = _iso_week_key(cursor)
        if wk not in used_weeks and streak > 0:
            # Auto-apply freeze for this missed day, only if the day before is active.
            prev_active = (cursor - timedelta(days=1)).isoformat() in activity_set
            if prev_active:
                used_weeks.add(wk)
                auto_applied.append(key)
                if streak_col is not None:
                    streak_col.update_one(
                        {'email': email},
                        {'$addToSet': {'usedWeeks': wk, 'autoApplied': key}},
                    )
                streak += 1
                cursor = cursor - timedelta(days=1)
                continue
        break

    # Best streak — quick scan through activity_log.
    best = 0
    if activity:
        run = 1
        for i in range(1, len(activity)):
            d_prev = datetime.fromisoformat(activity[i-1]).date()
            d_cur = datetime.fromisoformat(activity[i]).date()
            if (d_cur - d_prev).days == 1:
                run += 1
                best = max(best, run)
            else:
                run = 1
        best = max(best, run, streak)

    cur_week = _iso_week_key(today)
    freeze_available = cur_week not in used_weeks

    return jsonify({
        'success': True,
        'streak': streak,
        'best': best,
        'freezeAvailable': freeze_available,
        'currentWeek': cur_week,
        'autoApplied': auto_applied[-7:],
    })


@app.route('/api/streak/freeze', methods=['POST'])
def use_streak_freeze():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    streak_col = get_streak_freeze_col()
    if not db_connected or streak_col is None:
        return jsonify({'success': False, 'error': 'DB offline'}), 500
    email = session.get('user_email')
    today = datetime.utcnow().date()
    wk = _iso_week_key(today)
    doc = _ensure_streak_freezes_doc(email)
    if wk in doc.get('usedWeeks', []):
        return jsonify({'success': False, 'error': 'Freeze already used this week'}), 400
    streak_col.update_one(
        {'email': email},
        {'$addToSet': {'usedWeeks': wk, 'autoApplied': today.isoformat()}},
    )
    # Add to activity_log so dashboard reflects it.
    get_users_col().update_one({'email': email}, {'$addToSet': {'activity_log': today.isoformat()}})
    return jsonify({'success': True, 'usedFor': today.isoformat()})


# ─────────────────────────────────────────────────────────────
# CERTIFICATES — issue, look up, public verify (items 6, 7, 36)
# Each cert has a unique id used in the verification URL on the PDF QR.
# ─────────────────────────────────────────────────────────────

@app.route('/api/certificate', methods=['POST'])
def issue_certificate():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    course_id = data.get('courseId')
    course_title = data.get('courseTitle') or ''
    user_name = (data.get('userName') or session.get('user_name') or 'Yoga Practitioner').strip()
    score = int(data.get('score') or 0)
    poses = data.get('poses') or []  # [{name, mark}, ...]
    is_master = bool(data.get('isMaster'))

    if not course_id and not is_master:
        return jsonify({'success': False, 'error': 'courseId required'}), 400
    if score < 0 or score > 100:
        return jsonify({'success': False, 'error': 'Invalid score'}), 400

    cert_id = uuid.uuid4().hex[:12].upper()
    record = {
        'certId': cert_id,
        'email': session.get('user_email'),
        'userName': user_name,
        'courseId': course_id or 'master',
        'courseTitle': course_title or ('AsanMinds Master Programme' if is_master else course_id),
        'score': score,
        'poses': poses,
        'isMaster': is_master,
        'issuedAt': datetime.utcnow().isoformat(),
    }

    if db_connected:
        cert_col = get_certificates_col()
        if cert_col is not None:
            try:
                cert_col.update_one(
                    {'email': record['email'], 'courseId': record['courseId']},
                    {'$setOnInsert': record},
                    upsert=True,
                )
                existing = cert_col.find_one({'email': record['email'], 'courseId': record['courseId']})
                if existing and 'certId' in existing:
                    cert_id = existing['certId']
            except Exception as e:
                print(f'certificate save error: {e}')

    return jsonify({
        'success': True,
        'certId': cert_id,
        'verifyUrl': request.url_root.rstrip('/') + '/verify/' + cert_id,
    })


@app.route('/api/certificates', methods=['GET'])
def list_certificates():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    cert_col = get_certificates_col()
    if not db_connected or cert_col is None:
        return jsonify({'success': True, 'certificates': []})
    docs = list(cert_col.find({'email': session.get('user_email')}))
    out = []
    for d in docs:
        d.pop('_id', None)
        out.append(d)
    return jsonify({'success': True, 'certificates': out})


@app.route('/verify/<cert_id>')
def verify_certificate(cert_id):
    """Public verification page — anyone with the URL can confirm authenticity.

    Searches BOTH legacy and Google certificate collections so a verifier
    URL always works regardless of which login flow issued it.
    """
    if not db_connected:
        return _verify_html(None, cert_id, 'database-offline')
    upper_id = (cert_id or '').upper()
    cert = None
    for col in (certificates_col, g_certificates_col):
        if col is not None:
            cert = col.find_one({'certId': upper_id})
            if cert:
                break
    if not cert:
        return _verify_html(None, cert_id, 'not-found')
    return _verify_html(cert, cert_id, 'ok')


def _verify_html(cert, requested_id, state):
    # Escape every user-controllable string before inserting into HTML.
    # Names, course titles, pose names — all of these come from user input
    # (Google account name, our own static course list, our pose library)
    # and need defensive escaping in case any path lets a user inject HTML.
    esc = _html.escape
    name = esc(cert.get('userName') or '') if cert else ''
    course = esc(cert.get('courseTitle') or '') if cert else ''
    score_raw = cert.get('score') if cert else ''
    try:
        score = int(score_raw) if score_raw != '' else ''
    except Exception:
        score = ''
    issued = cert.get('issuedAt') if cert else ''
    poses = cert.get('poses') or [] if cert else []
    is_master = cert.get('isMaster') if cert else False
    issued_str = ''
    if issued:
        try:
            issued_str = datetime.fromisoformat(issued).strftime('%d %b %Y')
        except Exception:
            issued_str = esc(issued[:10])
    body_status = {
        'ok': 'verified',
        'not-found': 'not found',
        'database-offline': 'temporarily unavailable',
    }.get(state, 'unknown')

    rows_html = ''
    for r in poses:
        pose_name = esc(str(r.get('name', '')))
        try:
            pose_mark = int(r.get('mark', 0))
        except Exception:
            pose_mark = 0
        rows_html += f'<tr><td style="padding:8px 0;color:#14120E">{pose_name}</td><td style="text-align:right;color:#0F3D2E;font-weight:600">{pose_mark}%</td></tr>'

    cert_id_safe = esc(cert.get('certId', '')) if cert else ''
    requested_id_safe = esc(requested_id or '')

    if state == 'ok':
        body = f"""
        <span class=\"kicker\" style=\"color:#0F3D2E\">Authentic ✓</span>
        <h1 style=\"font-family:Fraunces,serif;font-size:42px;font-weight:300;color:#14120E;margin:8px 0 0\">{name}</h1>
        <p style=\"color:#4A453B;margin:6px 0 18px\">{course} {'(Master Certificate)' if is_master else ''}</p>
        <div style=\"background:#0F3D2E;color:#F5F2EB;border-radius:18px;padding:20px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap\">
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Final mark</span><div style=\"font-family:Fraunces,serif;font-size:36px;font-weight:300;line-height:1\">{score}%</div></div>
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Issued</span><div style=\"font-family:Fraunces,serif;font-size:18px;line-height:1.3;margin-top:8px\">{issued_str}</div></div>
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Cert id</span><div style=\"font-family:monospace;font-size:13px;margin-top:8px\">{cert_id_safe}</div></div>
        </div>
        {f'<table style="width:100%;margin-top:20px;border-collapse:collapse;font-size:14px"><tbody>{rows_html}</tbody></table>' if rows_html else ''}
        """
    else:
        body = f"""
        <span class=\"kicker\" style=\"color:#C2552F\">Not verifiable</span>
        <h1 style=\"font-family:Fraunces,serif;font-size:36px;font-weight:300;color:#14120E;margin:8px 0 0\">Certificate {body_status}</h1>
        <p style=\"color:#4A453B;margin:6px 0 0\">No certificate exists with id <code>{requested_id_safe}</code>.</p>
        """

    return f"""<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>Verify Certificate · AsanMinds</title>
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<link rel=\"icon\" type=\"image/svg+xml\" href=\"/assets/brand/favicon.svg\">
<link href=\"https://fonts.googleapis.com/css2?family=Fraunces:wght@300;400&family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\">
<style>body{{font-family:Inter,sans-serif;background:#F5F2EB;color:#14120E;margin:0;padding:32px;line-height:1.5}}
.kicker{{font-weight:500;font-size:11px;letter-spacing:0.22em;text-transform:uppercase}}
.card{{max-width:640px;margin:0 auto;background:#FFFFFF;border:1px solid #D4CCB8;border-radius:24px;padding:32px}}
.brand{{text-align:center;margin-bottom:16px;color:#7A7364}}</style>
</head><body>
<div class=\"brand kicker\">S U N D A Y · A S A N M I N D S</div>
<div class=\"card\">{body}</div>
<p style=\"text-align:center;color:#7A7364;font-size:12px;margin-top:16px\">Public certificate verification · Authentic certificates earned through AR-tested practice and theory examination.</p>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# CERTIFICATE EMAIL (item 6)
# Accepts a base64 PDF/PNG from the client and emails it via SendGrid.
# Falls back to "no email service" gracefully if SENDGRID_API_KEY isn't set.
# ─────────────────────────────────────────────────────────────

@app.route('/api/email/test', methods=['GET', 'POST'])
def email_test():
    """One-click SendGrid plumbing test.

    Sends a tiny "hello" email from SENDGRID_FROM_EMAIL to the currently
    signed-in user. No attachments. Returns a clear JSON describing exactly
    what worked and what didn't, so you can diagnose without hunting logs.
    """
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    api_key = os.environ.get('SENDGRID_API_KEY') or ''
    sender = os.environ.get('SENDGRID_FROM_EMAIL') or ''
    recipient = session.get('user_email') or ''
    user_name = session.get('user_name') or 'there'

    diagnostics = {
        'sendgrid_lib_installed': SENDGRID_AVAILABLE,
        'has_api_key': bool(api_key),
        'has_from_email': bool(sender),
        'from_email': sender,
        'to_email': recipient,
        'session_email_set': bool(recipient),
    }

    if not SENDGRID_AVAILABLE:
        return jsonify({'success': False, 'diagnostics': diagnostics,
                        'error': 'sendgrid Python package not installed on server.'}), 503
    if not api_key:
        return jsonify({'success': False, 'diagnostics': diagnostics,
                        'error': 'SENDGRID_API_KEY not set on Render.'}), 503
    if not sender:
        return jsonify({'success': False, 'diagnostics': diagnostics,
                        'error': 'SENDGRID_FROM_EMAIL not set on Render.'}), 503
    if not recipient:
        return jsonify({'success': False, 'diagnostics': diagnostics,
                        'error': 'No recipient email in session — sign in with Google first.'}), 400

    try:
        message = Mail(
            from_email=sender,
            to_emails=recipient,
            subject='AsanMinds — SendGrid test',
            html_content=f"""<p>Hi {_html.escape(user_name)},</p>
<p>This is a test email from your AsanMinds deployment to confirm SendGrid is wired up correctly.</p>
<p><b>From:</b> {_html.escape(sender)}<br><b>To:</b> {_html.escape(recipient)}</p>
<p>If you got this, the certificate email button will also work.</p>
<p>Namaste,<br>Sunday · AsanMinds</p>""")
        sg = SendGridAPIClient(api_key)
        resp = sg.send(message)
        diagnostics['sendgrid_status_code'] = getattr(resp, 'status_code', None)
        return jsonify({'success': True, 'diagnostics': diagnostics,
                        'message': f'Test email sent. Check the inbox of {recipient}.'})
    except Exception as e:
        err_str = str(e)
        diagnostics['exception'] = err_str[:200]
        if '403' in err_str or 'Forbidden' in err_str:
            hint = (f"SendGrid rejected the send (403). The from-email '{sender}' is not a "
                    "verified sender. Go to SendGrid → Settings → Sender Authentication → "
                    "Single Sender Verification and click the confirmation link in your inbox.")
        elif '401' in err_str or 'Unauthorized' in err_str:
            hint = 'SendGrid rejected the API key (401). Re-create SENDGRID_API_KEY with Full Access.'
        else:
            hint = 'See diagnostics.exception for the underlying error.'
        return jsonify({'success': False, 'diagnostics': diagnostics, 'error': hint}), 500


@app.route('/api/certificate/email', methods=['POST'])
def email_certificate():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}

    # Accept either {fileBase64, fileName} or {pdfDataUrl, pngDataUrl} —
    # the frontend currently sends the latter pair.
    pdf_url = data.get('pdfDataUrl') or ''
    png_url = data.get('pngDataUrl') or ''
    file_b64 = data.get('fileBase64') or pdf_url or png_url

    course_title = (data.get('courseTitle') or 'AsanMinds Certificate').strip()
    cert_id = (data.get('certId') or '').strip()

    if pdf_url:
        filename = data.get('fileName') or f'AsanMinds_Certificate_{cert_id or "cert"}.pdf'
        is_pdf = True
    elif png_url:
        filename = data.get('fileName') or f'AsanMinds_Certificate_{cert_id or "cert"}.png'
        is_pdf = False
    else:
        filename = (data.get('fileName') or 'AsanMinds_Certificate.pdf')
        is_pdf = filename.lower().endswith('.pdf')
    filename = filename.replace('"', '')

    score = int(data.get('score') or 0)
    user_email = session.get('user_email') or data.get('email')
    user_name = session.get('user_name') or 'practitioner'

    if not file_b64:
        return jsonify({'success': False, 'error': 'No certificate file received. Please reopen the certificate and try again.'}), 400
    if not user_email:
        return jsonify({'success': False, 'error': 'No recipient email on this account. Sign in with Google to fix this.'}), 400

    api_key = os.environ.get('SENDGRID_API_KEY') or ''
    sender = os.environ.get('SENDGRID_FROM_EMAIL') or 'no-reply@asanminds.app'
    if not (SENDGRID_AVAILABLE and api_key):
        return jsonify({'success': False, 'error': 'Email service is not configured on the server. Use the Download button instead.'}), 503

    try:
        # Strip "data:application/pdf;base64," prefix if present.
        clean_b64 = file_b64.split(',', 1)[-1]
        mime = 'application/pdf' if is_pdf else 'image/png'
        message = Mail(
            from_email=sender,
            to_emails=user_email,
            subject=f'Your AsanMinds Certificate: {course_title}',
            html_content=f"""<p>Dear {_html.escape(user_name)},</p>
<p>Congratulations on completing <b>{_html.escape(course_title)}</b> with a final mark of <b>{int(score)}%</b>.</p>
<p>Your certificate is attached. You can also share it from inside the app, or anyone can verify it at the URL on the certificate.</p>
<p>Namaste,<br>Sunday · AsanMinds</p>""")
        attachment = Attachment(
            FileContent(clean_b64),
            FileName(filename),
            FileType(mime),
            Disposition('attachment'),
        )
        message.add_attachment(attachment)
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return jsonify({'success': True})
    except Exception as e:
        err_str = str(e)
        print(f'sendgrid error: {err_str}')
        # Give a specific, actionable message so the user knows what to fix.
        if '403' in err_str or 'Forbidden' in err_str:
            msg = ('SendGrid rejected the send (403). Your SENDGRID_FROM_EMAIL is not verified '
                   'as a sender. Go to SendGrid → Settings → Sender Authentication → Single Sender '
                   'Verification → click the confirmation link in your inbox.')
        elif '401' in err_str or 'Unauthorized' in err_str:
            msg = 'SendGrid rejected the API key (401). Re-create the SENDGRID_API_KEY in Render with Full Access permissions.'
        elif '413' in err_str:
            msg = 'Certificate file is too large for email. Use the Download button instead.'
        else:
            msg = 'Email send failed; please use Download. (' + err_str[:80] + ')'
        return jsonify({'success': False, 'error': msg}), 500


# ─────────────────────────────────────────────────────────────
# USER PREFERENCES (items 33, 38, 39)
# Stays-signed-in flag, theme, daily reminder time, language.
# ─────────────────────────────────────────────────────────────

@app.route('/api/preferences', methods=['GET'])
def get_preferences():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    pref_col = get_preferences_col()
    if not db_connected or pref_col is None:
        return jsonify({'success': True, 'preferences': {}})
    doc = pref_col.find_one({'email': session.get('user_email')}) or {}
    doc.pop('_id', None)
    return jsonify({'success': True, 'preferences': doc.get('preferences') or {}})


@app.route('/api/preferences', methods=['PUT', 'POST'])
def save_preferences():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    prefs = data.get('preferences') or {}
    # Apply remember-me to the current session right away.
    if 'rememberMe' in prefs:
        session.permanent = bool(prefs['rememberMe'])
    pref_col = get_preferences_col()
    if not db_connected or pref_col is None:
        return jsonify({'success': True, 'note': 'DB offline'})
    pref_col.update_one(
        {'email': session.get('user_email')},
        {'$set': {'preferences': prefs, 'updatedAt': datetime.utcnow().isoformat()}},
        upsert=True,
    )
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────────
# WEB PUSH (item 37) — VAPID-based, optional
# Endpoints: GET /api/push/key, POST /api/push/subscribe, POST /api/push/test
# ─────────────────────────────────────────────────────────────

@app.route('/api/push/key', methods=['GET'])
def push_public_key():
    return jsonify({
        'enabled': bool(PUSH_AVAILABLE and os.environ.get('VAPID_PUBLIC_KEY')),
        'publicKey': os.environ.get('VAPID_PUBLIC_KEY') or '',
    })


@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    push_col = get_push_subs_col()
    if not db_connected or push_col is None:
        return jsonify({'success': False, 'error': 'DB offline'}), 500
    data = request.get_json(silent=True) or {}
    sub = data.get('subscription')
    reminder_time = data.get('reminderTime') or '07:00'
    if not sub or 'endpoint' not in sub:
        return jsonify({'success': False, 'error': 'Invalid subscription'}), 400
    push_col.update_one(
        {'email': session.get('user_email')},
        {'$set': {
            'subscription': sub,
            'reminderTime': reminder_time,
            'updatedAt': datetime.utcnow().isoformat(),
        }},
        upsert=True,
    )
    return jsonify({'success': True})


@app.route('/api/push/unsubscribe', methods=['POST'])
def push_unsubscribe():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    push_col = get_push_subs_col()
    if push_col is not None:
        push_col.delete_one({'email': session.get('user_email')})
    return jsonify({'success': True})


@app.route('/api/push/test', methods=['POST'])
def push_test():
    """Send a test notification to the current user. Returns success even when
    the push stack isn't installed — UI shows the right message."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    push_col = get_push_subs_col()
    if not (PUSH_AVAILABLE and os.environ.get('VAPID_PRIVATE_KEY') and push_col is not None):
        return jsonify({'success': False, 'error': 'Push not configured on server.'}), 503
    sub_doc = push_col.find_one({'email': session.get('user_email')})
    if not sub_doc or not sub_doc.get('subscription'):
        return jsonify({'success': False, 'error': 'No subscription saved.'}), 404
    try:
        webpush(
            subscription_info=sub_doc['subscription'],
            data=json.dumps({'title': 'Sunday', 'body': 'Your mat is waiting. Three minutes is enough.', 'url': '/home'}),
            vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
            vapid_claims={'sub': 'mailto:' + (os.environ.get('SENDGRID_FROM_EMAIL') or 'noreply@asanminds.app')},
        )
        return jsonify({'success': True})
    except Exception as e:
        print(f'push test error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────
# DELETE ACCOUNT (GDPR, item 39)
# Removes user document and all related artefacts.
# ─────────────────────────────────────────────────────────────

@app.route('/api/delete-account', methods=['POST', 'DELETE'])
def delete_account():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    email = session.get('user_email')
    if db_connected:
        try:
            # Wipe from BOTH databases — the user wants to be forgotten,
            # not just from one.
            for col in (users, get_users_col()):
                if col is not None:
                    col.delete_one({'email': email})
            for col in (
                certificates_col, course_progress_col, preferences_col,
                push_subs_col, streak_freeze_col,
                g_certificates_col, g_course_progress_col, g_preferences_col,
                g_push_subs_col, g_streak_freeze_col,
            ):
                if col is not None:
                    col.delete_many({'email': email})
        except Exception as e:
            print(f'delete-account error: {e}')
    session.clear()
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────────
# PRIVACY POLICY (item 38) — public, plain-English
# ─────────────────────────────────────────────────────────────

PRIVACY_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Privacy · AsanMinds</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/assets/brand/favicon.svg">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@300;400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>body{font-family:Inter,sans-serif;background:#F5F2EB;color:#14120E;margin:0;padding:48px 24px;line-height:1.65}
.wrap{max-width:720px;margin:0 auto}
h1{font-family:Fraunces,serif;font-size:48px;font-weight:300;letter-spacing:-0.02em;margin:0 0 6px}
h2{font-family:Fraunces,serif;font-size:24px;font-weight:400;margin-top:36px;color:#0F3D2E}
.kicker{color:#C2552F;font-weight:500;font-size:11px;letter-spacing:0.22em;text-transform:uppercase}
p{color:#4A453B;margin:10px 0}
ul{color:#4A453B;padding-left:20px}
li{margin:6px 0}
a{color:#0F3D2E}
.back{display:inline-block;margin-bottom:18px;color:#7A7364;text-decoration:none;font-size:12px;letter-spacing:0.2em;text-transform:uppercase}</style>
</head><body><div class="wrap">
<a class="back" href="/home">← Back to AsanMinds</a>
<span class="kicker">Privacy</span>
<h1>How we treat your data.</h1>
<p>AsanMinds is a yoga app built for students. We respect your time, your body and your data. Here is the entire policy in plain English.</p>

<h2>What stays on your device</h2>
<p>The pose detection runs entirely in your browser using TensorFlow.js. Your camera frames never leave your device. We do not record video, we do not save images, and we do not analyse anything outside the live frame in front of you.</p>

<h2>What we store on our server</h2>
<ul>
<li>Your name and email when you register.</li>
<li>The list of dates you practised on.</li>
<li>The poses you have completed and your scores.</li>
<li>Course progress and certificates you earn.</li>
<li>Preferences you set (theme, reminder time).</li>
<li>If you opt in to daily reminders, your push subscription token.</li>
</ul>

<h2>What we do not do</h2>
<ul>
<li>We do not sell your data.</li>
<li>We do not share it with third parties for advertising.</li>
<li>We do not use trackers like Google Analytics, Facebook Pixel, or similar.</li>
</ul>

<h2>Third parties we rely on</h2>
<ul>
<li><b>MongoDB Atlas</b> stores your account data, encrypted at rest.</li>
<li><b>Render</b> hosts the application.</li>
<li><b>OpenRouter / Gemini</b> answers questions when you talk to the AI assistant. We send the question and a short app context — never your camera frames.</li>
<li><b>SendGrid</b> sends your certificate to your email if you ask us to.</li>
</ul>

<h2>Your rights</h2>
<ul>
<li><b>Export.</b> Email us and we will send you a JSON of everything we hold about you.</li>
<li><b>Delete.</b> Use the "delete my account" button in Settings, or email us. We delete everything within 7 days, including backups within 30 days.</li>
<li><b>Object / restrict.</b> Just stop using the app. Inactive accounts are auto-pruned after 24 months of inactivity.</li>
</ul>

<h2>Children</h2>
<p>AsanMinds is intended for ages 13 and above. We do not knowingly collect data from children under 13.</p>

<h2>Contact</h2>
<p>For privacy questions, write to <a href="mailto:privacy@asanminds.app">privacy@asanminds.app</a>. We reply within 7 days.</p>

<p style="color:#7A7364;font-size:12px;margin-top:32px">Last updated: """ + datetime.utcnow().strftime('%d %B %Y') + """</p>
</div></body></html>"""


@app.route('/privacy')
def privacy_page():
    return PRIVACY_HTML


# ─────────────────────────────────────────────────────────────
# Org-admin SPA — separate from student /home and super-admin /admin.
# Only accessible to users whose role == 'org_admin'.
# ─────────────────────────────────────────────────────────────

@app.route('/org')
def org_page():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    if session.get('role') != 'org_admin':
        return redirect(url_for('home'))
    if not os.path.exists('org.html'):
        return "Error: org.html not found in app directory.", 500
    with open('org.html', 'r', encoding='utf-8') as f:
        content = f.read()
    response = app.make_response(content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


# ─────────────────────────────────────────────────────────────
# Multi-tenant routes (organizations, invitations, bulk import)
# Wired in via org_routes.py for clarity.
# ─────────────────────────────────────────────────────────────
try:
    from org_routes import register_org_routes
    _org_helpers = register_org_routes(app, {
        'organizations_col': organizations_col,
        'invitations_col': invitations_col,
        'admin_audit_col': admin_audit_col,
        'g_users': g_users,
        'users': users,
        'feedback_col': feedback_col,
        'certificates_col': certificates_col,
        'g_certificates_col': g_certificates_col,
        'course_progress_col': course_progress_col,
        'g_course_progress_col': g_course_progress_col,
        'push_subs_col': push_subs_col,
        'g_push_subs_col': g_push_subs_col,
        'sendgrid_send': _sendgrid_send,
        'webpush_send': _webpush_send,
        'admin_emails': ADMIN_EMAILS,
    })
    print('✓ Multi-tenant org routes registered')
except Exception as _e:
    print(f'⚠ Org routes failed to register: {_e}')
    _org_helpers = {}


# ═════════════════════════════════════════════════════════════
# ADMIN PANEL — routes + APIs
# ═════════════════════════════════════════════════════════════

ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Admin · AsanMinds</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/assets/brand/favicon.svg">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@300;400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
body{margin:0;background:#F5F2EB;color:#14120E;font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #D4CCB8;border-radius:22px;padding:40px 36px;max-width:420px;width:100%;box-shadow:0 24px 60px rgba(20,18,14,0.06)}
.brand-row{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.brand-dot{width:30px;height:30px;border-radius:8px;background:#0F3D2E;color:#F5F2EB;display:flex;align-items:center;justify-content:center;font-family:Fraunces,serif;font-size:15px}
.brand-word{font-family:Fraunces,serif;font-size:18px;font-weight:500;letter-spacing:-0.01em;color:#14120E}
.brand-tag{background:#C2552F;color:#F5F2EB;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase}
h1{font-family:Fraunces,serif;font-size:30px;font-weight:300;margin:6px 0 4px;letter-spacing:-0.02em}
.kicker{color:#C2552F;font-size:11px;letter-spacing:0.22em;text-transform:uppercase;font-weight:500}
.sub{color:#7A7364;font-size:13px;margin:0 0 22px}
label{display:block;font-size:11px;color:#7A7364;letter-spacing:0.18em;text-transform:uppercase;font-weight:500;margin:14px 0 6px}
input{width:100%;height:46px;padding:0 16px;border-radius:9999px;background:#EEE9DE;border:1px solid #D4CCB8;font-size:14px;font-family:inherit;outline:none;color:#14120E}
input:focus{border-color:#0F3D2E;background:#FFFFFF}
button{width:100%;height:46px;border-radius:9999px;border:0;background:#0F3D2E;color:#F5F2EB;font-weight:500;cursor:pointer;font-size:14px;margin-top:22px}
button:hover{background:#1F5A44}
.err{color:#C2552F;font-size:13px;margin-top:14px;background:rgba(194,85,47,0.08);padding:10px 14px;border-radius:10px;{{ 'display:none' if not error else '' }}}
.foot{margin-top:24px;color:#A8A294;font-size:12px;text-align:center}
.foot a{color:#7A7364;text-decoration:none}
.foot a:hover{color:#0F3D2E}
</style></head>
<body><form class="card" method="POST" action="/admin/login">
<div class="brand-row">
  <img src="/assets/brand/logo1.png" alt="AsanMinds" width="30" height="30" style="display:block;border-radius:8px;object-fit:contain">
  <span class="brand-word">sunday</span>
  <span class="brand-tag">Admin</span>
</div>
<span class="kicker">Restricted area</span>
<h1>Admin sign-in</h1>
<p class="sub">Enter your admin credentials. This is independent of the student login.</p>
<label>Email</label>
<input name="email" type="email" placeholder="admin@example.com" autofocus required value="{{ email }}">
<label>Password</label>
<input name="password" type="password" placeholder="••••••••" required>
<button type="submit">Sign in</button>
{{ '<p class=err>' + error + '</p>' if error else '' }}
<div class="foot">
  <a href="/">← Back to student app</a>
</div>
</form>
</body></html>"""


@app.route('/admin/login/diag')
def admin_login_diag():
    """Public diagnostic so the operator can see WHY admin login is rejecting.
    Tells you which env var is missing or empty WITHOUT leaking the values."""
    return jsonify({
        'admin_emails_set': bool(ADMIN_EMAILS),
        'admin_emails_count': len(ADMIN_EMAILS),
        'admin_password_set': bool(ADMIN_PASSWORD),
        'admin_password_length': len(ADMIN_PASSWORD) if ADMIN_PASSWORD else 0,
        'note': (
            'Both must be true. If admin_emails_count is 0, set ADMIN_EMAILS '
            'on Render (comma-separated). If admin_password_set is false, set '
            'ADMIN_PASSWORD on Render. Restart/redeploy after changes.'
        ),
    })


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login_page():
    """Standalone admin login — independent of Google or the student email flow.

    Validates against ADMIN_EMAILS allowlist + ADMIN_PASSWORD. On success,
    sets session['admin_unlocked'] = True and session['admin_email'] = the
    email entered. Does NOT touch the student session keys, so an admin
    can be signed in as themselves AND as a student in separate tabs.
    """
    error = ''
    submitted_email = ''
    if request.method == 'POST':
        submitted_email = (request.form.get('email') or '').strip().lower()
        pw = (request.form.get('password') or '').strip()
        # Refuse login entirely if the server hasn't been configured.
        if not ADMIN_EMAILS or not ADMIN_PASSWORD:
            error = 'Admin login is not configured on this server. Set ADMIN_EMAILS and ADMIN_PASSWORD env vars.'
        elif submitted_email and submitted_email in ADMIN_EMAILS and pw and _hmac.compare_digest(pw, ADMIN_PASSWORD):
            session.permanent = True
            session['admin_unlocked'] = True
            session['admin_email'] = submitted_email
            _audit('admin_login', submitted_email)
            return redirect('/admin')
        else:
            error = 'Wrong email or password.' if (submitted_email or pw) else 'Enter both email and password.'

    response = app.make_response(render_template_string(ADMIN_LOGIN_HTML, error=error, email=submitted_email))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


@app.route('/admin/logout')
def admin_logout():
    """Sign out from the admin panel only — leaves student session intact."""
    em = session.get('admin_email')
    session.pop('admin_unlocked', None)
    session.pop('admin_email', None)
    if em:
        _audit('admin_logout', em)
    return redirect(url_for('admin_login_page'))


# Legacy alias — old /admin/unlock URL still works.
@app.route('/admin/unlock', methods=['GET', 'POST'])
def admin_unlock_page():
    return redirect(url_for('admin_login_page'))


@app.route('/admin')
@admin_required
def admin_page():
    """Admin SPA — single HTML file that handles all admin views via hash routing."""
    if not os.path.exists('admin.html'):
        return "Error: admin.html not found", 500
    with open('admin.html', 'r', encoding='utf-8') as f:
        content = f.read()
    response = app.make_response(content)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


@app.route('/api/admin/me')
@admin_api_required
def admin_me():
    """Identity endpoint for the admin panel header (no student session required)."""
    return jsonify({
        'email': session.get('admin_email', ''),
        'unlocked': True,
    })


# ─────────────────────────────────────────────────
# ADMIN APIs
# ─────────────────────────────────────────────────

@app.route('/api/admin/kpi')
@admin_api_required
def admin_kpi():
    """Top-level KPIs + dashboard chart data."""
    all_users = _all_user_docs()
    total = len(all_users)
    google_count = sum(1 for u in all_users if u.get('auth_provider') == 'google')
    today = datetime.utcnow().date()
    cutoff_1d = (today - timedelta(days=1)).isoformat()
    cutoff_7d = (today - timedelta(days=7)).isoformat()
    cutoff_30d = (today - timedelta(days=30)).isoformat()

    active_1d = sum(1 for u in all_users if any(d >= cutoff_1d for d in (u.get('activity_log') or [])))
    active_7d = sum(1 for u in all_users if any(d >= cutoff_7d for d in (u.get('activity_log') or [])))

    # Certificates.
    total_certs = 0
    certs_30d = 0
    for col in (certificates_col, g_certificates_col):
        if col is not None:
            total_certs += col.count_documents({})
            certs_30d += col.count_documents({'issuedAt': {'$gte': cutoff_30d}})

    # Average completion across enrolled semesters.
    completion_pcts = []
    for col in (course_progress_col, g_course_progress_col):
        if col is None:
            continue
        for doc in col.find({}):
            progress = (doc.get('progress') or {}).get('courses') or {}
            for c in progress.values():
                poses = c.get('poses') or []
                if not poses:
                    continue
                done = sum(1 for p in poses if p.get('completed'))
                completion_pcts.append(round(done / len(poses) * 100))
    avg_completion = round(sum(completion_pcts) / len(completion_pcts)) if completion_pcts else 0

    # Daily active chart — last 30 days.
    dau_labels = []
    dau_values = []
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        dau_labels.append(datetime.fromisoformat(d).strftime('%d %b'))
        dau_values.append(sum(1 for u in all_users if d in (u.get('activity_log') or [])))

    # Funnel chart — students completed per semester.
    funnel_labels = ['Sem 3', 'Sem 4', 'Sem 5', 'Sem 6', 'Sem 7', 'Sem 8', 'Master']
    funnel_values = [0, 0, 0, 0, 0, 0, 0]
    sem_ids = ['sem3', 'sem4', 'sem5', 'sem6', 'sem7', 'sem8']
    for col in (course_progress_col, g_course_progress_col):
        if col is None:
            continue
        for doc in col.find({}):
            progress = (doc.get('progress') or {}).get('courses') or {}
            for idx, sid in enumerate(sem_ids):
                if (progress.get(sid) or {}).get('completed'):
                    funnel_values[idx] += 1
    for col in (certificates_col, g_certificates_col):
        if col is not None:
            funnel_values[6] += col.count_documents({'courseId': 'master'})

    return jsonify({
        'totalStudents': total,
        'googleStudents': google_count,
        'active1d': active_1d,
        'active7d': active_7d,
        'totalCerts': total_certs,
        'certs30d': certs_30d,
        'avgCompletion': avg_completion,
        'dauChart': {'labels': dau_labels, 'values': dau_values, 'label': 'Active users'},
        'funnelChart': {'labels': funnel_labels, 'values': funnel_values, 'label': 'Completed'},
    })


@app.route('/api/admin/students')
@admin_api_required
def admin_students():
    limit = int(request.args.get('limit', 0))
    sort = request.args.get('sort', '')
    rows = [_student_summary(u) for u in _all_user_docs()]
    if sort == '-created_at':
        rows.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    if limit > 0:
        rows = rows[:limit]
    return jsonify({'students': rows})


@app.route('/api/admin/student/<path:email>')
@admin_api_required
def admin_student_deep(email):
    email = email.lower().strip()
    user = None
    is_google = False
    if g_users is not None:
        u = g_users.find_one({'email': email})
        if u:
            user = u
            is_google = True
    if not user and users is not None:
        user = users.find_one({'email': email})
    if not user:
        return jsonify({'error': 'Not found'}), 404
    user.pop('_id', None)
    user['auth_provider'] = user.get('auth_provider', 'google' if is_google else 'email')
    if hasattr(user.get('created_at'), 'isoformat'):
        user['created_at'] = user['created_at'].isoformat()

    # Course progress.
    cp_col = g_course_progress_col if is_google else course_progress_col
    courses_out = []
    sem_meta = [
        {'id': 'sem3', 'n': 3, 'name': 'Foundations'},
        {'id': 'sem4', 'n': 4, 'name': 'Grounding'},
        {'id': 'sem5', 'n': 5, 'name': 'Restoration'},
        {'id': 'sem6', 'n': 6, 'name': 'Strength'},
        {'id': 'sem7', 'n': 7, 'name': 'Lateral Body'},
        {'id': 'sem8', 'n': 8, 'name': 'Advanced Mastery'},
    ]
    progress = {}
    if cp_col is not None:
        cp_doc = cp_col.find_one({'email': email}) or {}
        progress = (cp_doc.get('progress') or {}).get('courses') or {}
    for sm in sem_meta:
        c = progress.get(sm['id']) or {}
        poses = c.get('poses') or []
        total_poses = len(poses)
        done_poses = sum(1 for p in poses if p.get('completed'))
        ar_done = sum(1 for p in poses if p.get('arPassed'))
        quiz_done = sum(1 for p in poses if p.get('quizPassed'))
        pct = round(done_poses / total_poses * 100) if total_poses else 0
        courses_out.append({
            'id': sm['id'],
            'semesterNumber': sm['n'],
            'name': sm['name'],
            'completed': bool(c.get('completed')),
            'locked': not poses or all(p.get('locked', True) for p in poses),
            'finalScore': c.get('finalScore'),
            'totalPoses': total_poses,
            'donePoses': done_poses,
            'arDone': ar_done,
            'quizDone': quiz_done,
            'pct': pct,
            'poses': [
                {
                    'name': p.get('name'),
                    'sanskrit': p.get('sanskrit', ''),
                    'completed': bool(p.get('completed')),
                    'arPassed': bool(p.get('arPassed')),
                    'quizPassed': bool(p.get('quizPassed')),
                    'arBest': p.get('arBest', 0),
                    'quizBest': p.get('quizBest', 0),
                    'finalScore': p.get('finalScore', 0),
                    'locked': bool(p.get('locked', True)),
                }
                for p in poses
            ],
        })

    # Certificates.
    cert_col = g_certificates_col if is_google else certificates_col
    certs = []
    if cert_col is not None:
        for c in cert_col.find({'email': email}):
            c.pop('_id', None)
            certs.append(c)
    certs.sort(key=lambda c: c.get('issuedAt', ''), reverse=True)

    # Top poses.
    completed_asanas = user.get('completed_asanas', {}) or {}
    total_sessions = sum(int(v or 0) for v in completed_asanas.values())
    top_poses = sorted(completed_asanas.items(), key=lambda x: -int(x[1] or 0))[:8]
    max_count = max((int(v) for _, v in top_poses), default=1)
    top_poses_out = [{'name': n, 'count': int(c), 'pct': round(int(c) / max_count * 100)} for n, c in top_poses if int(c) > 0]

    # Recent sessions.
    recent_sessions = (user.get('session_history') or [])[-60:]
    recent_sessions = list(reversed(recent_sessions))

    # Streak.
    activity = sorted(user.get('activity_log', []) or [])
    best, cur, prev = 0, 0, None
    for d in activity:
        try:
            t = datetime.fromisoformat(d).date()
        except Exception:
            continue
        if prev and (t - prev).days == 1:
            cur += 1
        else:
            cur = 1
        if cur > best:
            best = cur
        prev = t

    # Feedback.
    feedback_rows = []
    if feedback_col is not None:
        for f in feedback_col.find({'email': email}).sort('submitted_at', -1):
            f.pop('_id', None)
            feedback_rows.append(f)

    return jsonify({
        'user': user,
        'courses': courses_out,
        'certificates': certs,
        'topPoses': top_poses_out,
        'recentSessions': recent_sessions,
        'totalSessions': total_sessions,
        'activeDays': len(activity),
        'bestStreak': best,
        'feedback': feedback_rows,
    })


@app.route('/api/admin/feedback')
@admin_api_required
def admin_feedback():
    """All feedback joined with user profile data for display."""
    if feedback_col is None:
        return jsonify({'feedback': []})
    rows = []
    user_cache = {}
    for f in feedback_col.find({}).sort('submitted_at', -1).limit(500):
        f.pop('_id', None)
        em = f.get('email', '')
        if em and em not in user_cache:
            u = None
            if g_users is not None:
                u = g_users.find_one({'email': em})
            if not u and users is not None:
                u = users.find_one({'email': em})
            user_cache[em] = u or {}
        u = user_cache.get(em, {})
        f['name'] = u.get('name', em.split('@')[0] if em else '')
        f['picture'] = u.get('picture', '')
        rows.append(f)
    return jsonify({'feedback': rows})


@app.route('/api/admin/certificates')
@admin_api_required
def admin_certificates():
    rows = []
    for col in (certificates_col, g_certificates_col):
        if col is not None:
            for c in col.find({}).sort('issuedAt', -1).limit(500):
                c.pop('_id', None)
                rows.append(c)
    rows.sort(key=lambda c: c.get('issuedAt', ''), reverse=True)
    return jsonify({'certificates': rows})


@app.route('/api/admin/analytics')
@admin_api_required
def admin_analytics():
    all_users = _all_user_docs()
    today = datetime.utcnow().date()

    # Pose popularity.
    pose_totals = {}
    for u in all_users:
        for name, count in (u.get('completed_asanas') or {}).items():
            pose_totals[name] = pose_totals.get(name, 0) + int(count or 0)
    top_poses = sorted(pose_totals.items(), key=lambda x: -x[1])[:12]
    poses_chart = {'labels': [n for n, _ in top_poses], 'values': [c for _, c in top_poses], 'label': 'Sessions'}

    # Streak distribution.
    buckets = [(0, '0'), (1, '1-2'), (3, '3-6'), (7, '7-13'), (14, '14-29'), (30, '30+')]
    bucket_counts = [0] * len(buckets)
    for u in all_users:
        activity = sorted(u.get('activity_log', []) or [])
        best, cur, prev = 0, 0, None
        for d in activity:
            try:
                t = datetime.fromisoformat(d).date()
            except Exception:
                continue
            if prev and (t - prev).days == 1:
                cur += 1
            else:
                cur = 1
            if cur > best:
                best = cur
            prev = t
        for idx in range(len(buckets) - 1, -1, -1):
            if best >= buckets[idx][0]:
                bucket_counts[idx] += 1
                break
    streaks_chart = {'labels': [b[1] for b in buckets], 'values': bucket_counts, 'label': 'Users'}

    # Cohort retention — D1, D7, D14, D30.
    days_after = [1, 7, 14, 30]
    retention = []
    for d in days_after:
        eligible, retained = 0, 0
        cutoff = (today - timedelta(days=d)).isoformat()
        for u in all_users:
            created = u.get('created_at')
            if hasattr(created, 'isoformat'):
                created_iso = created.isoformat()[:10]
            elif isinstance(created, str):
                created_iso = created[:10]
            else:
                continue
            if created_iso > cutoff:
                continue
            eligible += 1
            activity = u.get('activity_log') or []
            target_after = (datetime.fromisoformat(created_iso).date() + timedelta(days=d-1)).isoformat()
            target_until = (datetime.fromisoformat(created_iso).date() + timedelta(days=d+1)).isoformat()
            if any(target_after <= a <= target_until for a in activity):
                retained += 1
        retention.append(round(retained / eligible * 100) if eligible else 0)
    retention_chart = {'labels': [f'D{d}' for d in days_after], 'values': retention, 'label': '% retained'}

    # Sign-ups by week — last 12 weeks.
    weeks = []
    week_counts = []
    for i in range(11, -1, -1):
        wk_end = today - timedelta(days=i*7)
        wk_start = wk_end - timedelta(days=6)
        label = wk_start.strftime('%d %b')
        weeks.append(label)
        cnt = 0
        for u in all_users:
            created = u.get('created_at')
            if hasattr(created, 'isoformat'):
                ci = created.isoformat()[:10]
            elif isinstance(created, str):
                ci = created[:10]
            else:
                continue
            if wk_start.isoformat() <= ci <= wk_end.isoformat():
                cnt += 1
        week_counts.append(cnt)
    signups_chart = {'labels': weeks, 'values': week_counts, 'label': 'Sign-ups'}

    return jsonify({
        'poses': poses_chart,
        'streaks': streaks_chart,
        'retention': retention_chart,
        'signups': signups_chart,
    })


@app.route('/api/admin/notify/<path:email>', methods=['POST'])
@admin_api_required
def admin_notify_one(email):
    """Push a notification to a single user."""
    if not (PUSH_AVAILABLE and os.environ.get('VAPID_PRIVATE_KEY')):
        return jsonify({'success': False, 'error': 'Push not configured.'}), 503
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or 'A note from your coach').strip()[:80]
    body = (data.get('body') or '').strip()[:300]
    sub_doc = None
    if g_push_subs_col is not None:
        sub_doc = g_push_subs_col.find_one({'email': email})
    if not sub_doc and push_subs_col is not None:
        sub_doc = push_subs_col.find_one({'email': email})
    if not sub_doc:
        return jsonify({'success': False, 'error': 'User has no active push subscription.'}), 404
    try:
        webpush(
            subscription_info=sub_doc['subscription'],
            data=json.dumps({'title': title, 'body': body, 'url': '/home'}),
            vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
            vapid_claims={'sub': 'mailto:' + (os.environ.get('SENDGRID_FROM_EMAIL') or 'noreply@asanminds.app')},
        )
        _audit('notify_one', email, {'title': title})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500


@app.route('/api/admin/broadcast', methods=['POST'])
@admin_api_required
def admin_broadcast():
    """Send the same push to every subscribed user."""
    if not (PUSH_AVAILABLE and os.environ.get('VAPID_PRIVATE_KEY')):
        return jsonify({'success': False, 'error': 'Push not configured.'}), 503
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or 'Sunday is waiting').strip()[:80]
    body = (data.get('body') or '').strip()[:300]
    attempted, delivered, failures = 0, 0, []
    for col in (g_push_subs_col, push_subs_col):
        if col is None:
            continue
        for doc in col.find({}):
            attempted += 1
            try:
                webpush(
                    subscription_info=doc['subscription'],
                    data=json.dumps({'title': title, 'body': body, 'url': '/home'}),
                    vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                    vapid_claims={'sub': 'mailto:' + (os.environ.get('SENDGRID_FROM_EMAIL') or 'noreply@asanminds.app')},
                )
                delivered += 1
            except Exception as e:
                failures.append({'email': doc.get('email'), 'err': str(e)[:80]})
    _audit('broadcast', '', {'title': title, 'attempted': attempted, 'delivered': delivered})
    return jsonify({'success': True, 'attempted': attempted, 'delivered': delivered, 'failures': failures[:20]})


@app.route('/api/admin/edit/<path:email>', methods=['POST', 'PUT'])
@admin_api_required
def admin_edit_user(email):
    """Edit a student's mutable fields (name, picture). Email is the
    primary key so it cannot be changed — that would require migrating
    every related collection. If you need to change an email, delete and
    let the user sign up again with the new one.
    """
    email = email.lower().strip()
    data = request.get_json(silent=True) or {}
    update = {}
    if 'name' in data:
        update['name'] = (data.get('name') or '').strip()[:120]
    if 'picture' in data:
        update['picture'] = (data.get('picture') or '').strip()[:500]
    if 'auth_provider' in data and data['auth_provider'] in ('google', 'email'):
        update['auth_provider'] = data['auth_provider']
    if not update:
        return jsonify({'success': False, 'error': 'Nothing to update.'}), 400

    matched = 0
    for col in (g_users, users):
        if col is None:
            continue
        res = col.update_one({'email': email}, {'$set': update})
        matched += res.matched_count
    if not matched:
        return jsonify({'success': False, 'error': 'User not found.'}), 404
    _audit('edit_user', email, update)
    return jsonify({'success': True, 'updated': update})


@app.route('/api/admin/reset/<path:email>', methods=['POST'])
@admin_api_required
def admin_reset_progress(email):
    """Wipe a user's course progress (keep their certificates and account)."""
    email = email.lower().strip()
    deleted = 0
    for col in (course_progress_col, g_course_progress_col):
        if col is not None:
            res = col.delete_one({'email': email})
            deleted += res.deleted_count
    # Also reset their per-pose AR scores in the user doc itself.
    for col in (g_users, users):
        if col is not None:
            col.update_one({'email': email}, {'$set': {'completed_asanas': {}, 'session_history': []}})
    _audit('reset_progress', email)
    return jsonify({'success': True, 'deleted': deleted})


@app.route('/api/admin/delete/<path:email>', methods=['POST', 'DELETE'])
@admin_api_required
def admin_delete_user(email):
    """Permanently delete a user — wipes EVERY trace from BOTH databases.

    Removes:
      • user document (users + g_users)
      • course progress
      • certificates
      • preferences
      • push subscriptions
      • streak freezes
      • feedback submissions
      • audit log entries targeting this user (if --hard)
    """
    email = email.lower().strip()
    counts = {}
    # User documents.
    for label, col in [('users', users), ('g_users', g_users)]:
        if col is not None:
            res = col.delete_one({'email': email})
            counts[label] = res.deleted_count
    # All related collections.
    for label, col in [
        ('certificates_col', certificates_col),
        ('course_progress_col', course_progress_col),
        ('preferences_col', preferences_col),
        ('push_subs_col', push_subs_col),
        ('streak_freeze_col', streak_freeze_col),
        ('g_certificates_col', g_certificates_col),
        ('g_course_progress_col', g_course_progress_col),
        ('g_preferences_col', g_preferences_col),
        ('g_push_subs_col', g_push_subs_col),
        ('g_streak_freeze_col', g_streak_freeze_col),
        ('feedback_col', feedback_col),
    ]:
        if col is not None:
            res = col.delete_many({'email': email})
            counts[label] = res.deleted_count
    _audit('delete_user_hard', email, counts)
    return jsonify({'success': True, 'deleted': counts, 'note': 'User permanently removed from all collections.'})


# ─────────────────────────────────────────────────
# LIVE STUDENT CAMERA — snapshot relay
# ─────────────────────────────────────────────────
# A student in an active AR session POSTs a JPEG frame every ~1.5s to
# /api/live/upload. The latest frame per student lives in memory only and
# expires after 8s of inactivity (so the moment the student stops, they're
# instantly offline from the admin's POV).
#
# Reading the frames requires both the admin session AND a separate live-view
# password sent in the X-Live-Pass header. The password is checked with
# constant-time comparison and is never sent to any client.

def _live_pass_ok():
    """Constant-time compare of the live-view password from request header."""
    if not LIVE_VIEW_PASSWORD:
        return False
    supplied = request.headers.get('X-Live-Pass') or request.cookies.get('live_pass') or ''
    return _hmac.compare_digest(supplied, LIVE_VIEW_PASSWORD)


@app.route('/api/live/upload', methods=['POST'])
def live_upload_frame():
    """Student-side: pushes the latest camera frame.

    Body: { frame: 'data:image/jpeg;base64,...', pose, score }.
    No admin auth required — the student is uploading their own frame.
    Email is taken from the session, not the body, to prevent spoofing.
    Frames are stored in MongoDB so they survive worker boundaries on
    Render (gunicorn with >1 worker would lose in-memory state).
    """
    if not session.get('logged_in'):
        return jsonify({'success': False}), 401
    email = (session.get('user_email') or '').lower()
    if not email or live_frames_col is None:
        return jsonify({'success': False}), 401
    data = request.get_json(silent=True) or {}
    frame_str = data.get('frame') or ''
    pose = (data.get('pose') or '')[:60]
    try:
        score = int(data.get('score') or 0)
    except Exception:
        score = 0
    if not frame_str.startswith('data:image/jpeg;base64,'):
        return jsonify({'success': False, 'error': 'invalid frame'}), 400
    try:
        raw = _b64stream.b64decode(frame_str.split(',', 1)[1])
    except Exception:
        return jsonify({'success': False, 'error': 'bad base64'}), 400
    # Reject frames over 200 KB to bound storage.
    if len(raw) > 200 * 1024:
        return jsonify({'success': False, 'error': 'frame too large'}), 413

    now = datetime.utcnow()
    expires = now + timedelta(seconds=30)  # TTL index reaps after this
    try:
        live_frames_col.update_one(
            {'email': email},
            {'$set': {
                'email': email,
                'frame': _BsonBinary(raw),
                'pose': pose,
                'score': score,
                'updatedAt': now,
                'expiresAt': expires,
            }},
            upsert=True,
        )
    except Exception as e:
        print(f'live frame upload error: {e}')
        return jsonify({'success': False, 'error': 'store error'}), 500
    return jsonify({'success': True})


@app.route('/api/live/stop', methods=['POST'])
def live_stop():
    """Student-side: explicit signal that the AR session has ended."""
    if not session.get('logged_in') or live_frames_col is None:
        return jsonify({'success': False}), 401
    email = (session.get('user_email') or '').lower()
    try:
        live_frames_col.delete_one({'email': email})
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/admin/live/status')
@admin_api_required
def admin_live_status():
    """Returns which students currently have a live frame available."""
    out = {}
    if live_frames_col is None:
        return jsonify({'live': out, 'note': 'live_frames_col is None'})
    cutoff = datetime.utcnow() - timedelta(seconds=LIVE_FRAME_TTL)
    try:
        for doc in live_frames_col.find(
            {'updatedAt': {'$gte': cutoff}},
            {'email': 1, 'pose': 1, 'score': 1, 'updatedAt': 1, '_id': 0},
        ):
            em = doc.get('email')
            if not em:
                continue
            age = (datetime.utcnow() - doc['updatedAt']).total_seconds()
            out[em] = {
                'pose': doc.get('pose', ''),
                'score': doc.get('score', 0),
                'age': round(age, 1),
            }
    except Exception as e:
        print(f'live status error: {e}')
        return jsonify({'live': out, 'error': str(e)[:200]})
    return jsonify({'live': out})


@app.route('/api/admin/live/diag')
@admin_api_required
def admin_live_diag():
    """Diagnostics endpoint — tells admin everything about the live pipeline."""
    info = {
        'live_frames_col_ready': live_frames_col is not None,
        'live_view_password_set': bool(LIVE_VIEW_PASSWORD),
        'admin_pass_cookie_present': bool(request.cookies.get('live_pass')),
        'admin_pass_valid': _live_pass_ok(),
        'frame_ttl_seconds': LIVE_FRAME_TTL,
    }
    if live_frames_col is not None:
        try:
            cutoff = datetime.utcnow() - timedelta(seconds=LIVE_FRAME_TTL)
            total = live_frames_col.count_documents({})
            fresh = live_frames_col.count_documents({'updatedAt': {'$gte': cutoff}})
            info['total_frames_in_db'] = total
            info['fresh_frames'] = fresh
            sample = list(live_frames_col.find({}, {'email': 1, 'pose': 1, 'updatedAt': 1, '_id': 0}).sort('updatedAt', -1).limit(5))
            info['recent'] = [
                {
                    'email': s.get('email'),
                    'pose': s.get('pose'),
                    'age_seconds': round((datetime.utcnow() - s['updatedAt']).total_seconds(), 1),
                }
                for s in sample
            ]
        except Exception as e:
            info['error'] = str(e)[:200]
    return jsonify(info)


@app.route('/api/admin/live/check', methods=['POST'])
@admin_api_required
def admin_live_check():
    """Validates the live-view password. Sets a short-lived cookie on success
    so the admin's browser can fetch frames without re-typing the password.
    The password itself is never returned to the client.
    """
    data = request.get_json(silent=True) or {}
    pw = (data.get('password') or '').strip()
    if not LIVE_VIEW_PASSWORD or not _hmac.compare_digest(pw, LIVE_VIEW_PASSWORD):
        _audit('live_password_fail', '', {'len': len(pw)})
        return jsonify({'success': False, 'error': 'Wrong password'}), 401
    response = jsonify({'success': True})
    response.set_cookie(
        'live_pass',
        pw,
        max_age=30 * 60,
        path='/api/admin/live/',
        httponly=True,
        secure=bool(os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production'),
        samesite='Lax',
    )
    return response


@app.route('/api/admin/live/frame/<path:email>')
@admin_api_required
def admin_live_frame(email):
    """Returns the latest JPEG for a given student.

    Requires admin session + live-view password (header or cookie).
    Audited on first fetch per session.
    """
    if not _live_pass_ok():
        return jsonify({'error': 'Live-view password required'}), 401
    if live_frames_col is None:
        return jsonify({'error': 'DB offline'}), 503
    email = (email or '').lower().strip()
    cutoff = datetime.utcnow() - timedelta(seconds=LIVE_FRAME_TTL)
    doc = live_frames_col.find_one({'email': email, 'updatedAt': {'$gte': cutoff}})
    if not doc:
        return jsonify({'error': 'No active session'}), 404
    if not session.get('live_audit_for_' + email):
        session['live_audit_for_' + email] = True
        _audit('live_view_start', email, {'pose': doc.get('pose', '')})
    raw = doc.get('frame') or b''
    # PyMongo returns bytes wrapped — pull the actual binary.
    if hasattr(raw, 'tobytes'):
        raw = raw.tobytes()
    response = app.make_response(bytes(raw))
    response.headers['Content-Type'] = 'image/jpeg'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/admin/export/<kind>.csv')
@admin_required
def admin_export(kind):
    import csv, io
    # CSV-injection guard — values starting with =, +, -, or @ are
    # interpreted as formulas in Excel/Google Sheets. Prefix with a tab
    # to neutralise without changing the visible value.
    def _safe(v):
        s = '' if v is None else str(v)
        if s and s[0] in ('=', '+', '-', '@'):
            return '\t' + s
        return s

    out = io.StringIO()
    w = csv.writer(out)
    if kind == 'students':
        w.writerow(['email', 'name', 'auth_provider', 'created_at', 'last_active', 'active_days', 'best_streak', 'sems_completed', 'has_master', 'total_sessions', 'poses_learned'])
        for s in (_student_summary(u) for u in _all_user_docs()):
            w.writerow([_safe(s['email']), _safe(s['name']), _safe(s['auth_provider']), _safe(s['created_at'] or ''), _safe(s['last_active'] or ''), s['active_days'], s['best_streak'], s['sems_completed'], 'yes' if s['has_master'] else 'no', s['total_sessions'], s['poses_learned']])
    elif kind == 'feedback':
        w.writerow(['email', 'rating', 'course_id', 'helpful', 'hardest', 'nps', 'submitted_at'])
        if feedback_col is not None:
            for f in feedback_col.find({}):
                w.writerow([_safe(f.get('email', '')), f.get('rating', ''), _safe(f.get('course_id', '')), _safe(f.get('helpful', '')), _safe(f.get('hardest', '')), _safe(f.get('nps', '')), _safe(f.get('submitted_at', ''))])
    elif kind == 'sessions':
        w.writerow(['email', 'pose', 'peak_score', 'duration_s', 'ts'])
        for u in _all_user_docs():
            for s in (u.get('session_history') or []):
                w.writerow([_safe(u.get('email', '')), _safe(s.get('pose', '')), s.get('peakScore', ''), s.get('durationS', ''), _safe(s.get('ts', ''))])
    else:
        return 'Unknown export', 404

    response = app.make_response(out.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={kind}.csv'
    _audit('export_csv', '', {'kind': kind})
    return response


# ─────────────────────────────────────────────────
# FEEDBACK — student-side submission
# ─────────────────────────────────────────────────

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if feedback_col is None:
        return jsonify({'success': False, 'error': 'DB offline'}), 500
    data = request.get_json(silent=True) or {}
    rating = data.get('rating')
    try:
        rating = int(rating)
    except Exception:
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({'success': False, 'error': 'Rating must be 1-5'}), 400
    feedback_col.insert_one({
        'email': session.get('user_email'),
        'auth_provider': session.get('auth_provider', 'email'),
        'rating': rating,
        'course_id': (data.get('course_id') or 'general')[:40],
        'helpful': (data.get('helpful') or '').strip()[:1000],
        'hardest': (data.get('hardest') or '').strip()[:1000],
        'nps': (data.get('nps') or '').strip().lower()[:10] if data.get('nps') in ('yes', 'maybe', 'no') else '',
        'submitted_at': datetime.utcnow().isoformat(),
    })
    return jsonify({'success': True})


@app.route('/api/feedback/mine')
def my_feedback():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if feedback_col is None:
        return jsonify({'success': True, 'feedback': []})
    rows = []
    for f in feedback_col.find({'email': session.get('user_email')}).sort('submitted_at', -1):
        f.pop('_id', None)
        rows.append(f)
    return jsonify({'success': True, 'feedback': rows})


if __name__ == '__main__':
    # Use dynamic port for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')