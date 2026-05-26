from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session, send_from_directory
import pymongo
from datetime import datetime, timedelta
from collections import defaultdict
import os
import json
import uuid
import secrets
import urllib.request
import urllib.error

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

app = Flask(__name__)
# Use environment variable for secret key, fallback ONLY for local dev
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-this-in-render')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
# Persistent sessions — supports the "stay signed in for 30 days" toggle.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# Mark cookies secure when running behind https (Render does this).
if os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True

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

# MongoDB connection
db_connected = False
# Priority: ENV variable for Render/Production
mongodb_uri = os.environ.get('MONGO_URI', "mongodb+srv://anv:anv@anv.thrp6za.mongodb.net/?appName=anv")

try:
    client = pymongo.MongoClient(mongodb_uri)
    # Ensure the correct database name is used
    db = client.get_database("face_auth")
    users = db.users
    certificates_col = db.certificates
    course_progress_col = db.course_progress
    preferences_col = db.preferences
    push_subs_col = db.push_subscriptions
    streak_freeze_col = db.streak_freezes
    client.admin.command('ping')
    print("✓ MongoDB connected successfully")
    db_connected = True
except Exception as e:
    print(f"✗ MongoDB connection failed: {e}")
    print("App will run without DB (profile features disabled)")
    certificates_col = course_progress_col = preferences_col = None
    push_subs_col = streak_freeze_col = None

# Updated INDEX_HTML (with /home redirects)
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SUNDAY - Yoga Wellness Platform</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#2563eb">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="apple-touch-icon" href="/assets/logo.png">
    <link rel="icon" type="image/png" href="/assets/logo.png">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; }
        .bg-mesh {
            background-color: #0c0e12;
            background-image: 
                radial-gradient(at 0% 0%, rgba(37, 99, 235, 0.1) 0, transparent 50%), 
                radial-gradient(at 100% 0%, rgba(255, 235, 59, 0.05) 0, transparent 50%);
        }
        .glass {
            background: rgba(30, 32, 38, 0.4);
            backdrop-filter: blur(25px);
            border: 1px solid rgba(255, 255, 255, 0.03);
            box-shadow: 0 40px 100px -20px rgba(0, 0, 0, 0.7);
        }
        .input-glow:focus {
            box-shadow: 0 0 20px rgba(37, 99, 235, 0.2);
            border-color: #42A5F5;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(15px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeIn { animation: fadeIn 1s cubic-bezier(0.2, 0.8, 0.2, 1) forwards; }
        
        /* Shimmering Loader */
        .premium-loader {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            border: 3px solid rgba(66, 165, 245, 0.1);
            border-top-color: #42A5F5;
            animation: spin 1s cubic-bezier(0.68, -0.55, 0.265, 1.55) infinite;
        }
        .premium-loader::after {
            content: '';
            position: absolute;
            inset: 8px;
            border-radius: 50%;
            border: 3px solid rgba(255, 235, 59, 0.1);
            border-bottom-color: #FFEB3B;
            animation: spin 1.5s linear infinite reverse;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body class="bg-mesh min-h-screen flex items-center justify-center p-6">
    <div class="w-full max-w-lg animate-fadeIn">
        <div class="text-center mb-10">
            <div class="inline-flex items-center justify-center w-20 h-20 bg-gradient-to-br from-blue-600 to-indigo-700 rounded-3xl shadow-2xl shadow-blue-500/20 mb-6 rotate-3 overflow-hidden p-2 border border-white/10">
                <img src="/assets/logo.png" alt="SUNDAY Logo" class="w-full h-full object-contain">
            </div>
            <h1 class="text-6xl font-black text-white tracking-tighter mb-2">SUNDAY</h1>
            <p class="text-gray-500 text-lg font-medium tracking-wide">ELEVATE YOUR PRACTICE</p>
        </div>

        <div class="glass rounded-[3rem] p-10 relative overflow-hidden">
            <div class="absolute -top-24 -right-24 w-48 h-48 bg-blue-600/10 rounded-full blur-3xl"></div>
            <div class="absolute -bottom-24 -left-24 w-48 h-48 bg-yellow-400/5 rounded-full blur-3xl"></div>
            
            <!-- Login Form -->
            <div id="login-form">
                <h2 class="text-3xl font-black text-white mb-8 border-b border-white/5 pb-4">Welcome Back</h2>
                <form id="login-form-submit" class="space-y-6">
                    <div>
                        <label class="block text-gray-500 text-xs font-black uppercase tracking-widest mb-2 px-1">Full Name</label>
                        <input id="login-name" type="text" placeholder="John Doe" required
                            class="w-full px-6 py-4 bg-black/30 border border-white/5 rounded-2xl text-white placeholder-gray-700 focus:outline-none input-glow transition-all">
                    </div>
                    <div>
                        <label class="block text-gray-500 text-xs font-black uppercase tracking-widest mb-2 px-1">Email Address</label>
                        <input id="login-email" type="email" placeholder="john@example.com" required
                            class="w-full px-6 py-4 bg-black/30 border border-white/5 rounded-2xl text-white placeholder-gray-700 focus:outline-none input-glow transition-all">
                    </div>
                    <button type="submit" class="w-full py-5 bg-blue-600 hover:bg-blue-500 text-white font-black rounded-2xl transition-all shadow-xl shadow-blue-600/20 transform hover:-translate-y-1 active:scale-95 uppercase tracking-widest">
                        Sign In
                    </button>
                </form>
                <div id="login-google" style="display:none; margin-top:24px">
                    <div style="display:flex; align-items:center; gap:10px; color:#6B7280; font-size:11px; letter-spacing:0.18em; text-transform:uppercase; margin-bottom:14px">
                        <span style="flex:1; height:1px; background:rgba(255,255,255,0.08)"></span>
                        <span>Or</span>
                        <span style="flex:1; height:1px; background:rgba(255,255,255,0.08)"></span>
                    </div>
                    <div id="g-host-login" style="display:flex; justify-content:center"></div>
                </div>
                <p class="text-center mt-10 text-gray-600 text-sm">
                    New to SUNDAY? 
                    <button id="show-register" class="text-blue-400 hover:text-blue-300 font-black ml-1 uppercase text-xs tracking-widest">Create Account</button>
                </p>
                <p id="login-error" class="mt-6 text-center text-red-400 hidden bg-red-400/10 py-4 rounded-2xl border border-red-400/20 text-sm font-bold"></p>
            </div>

            <!-- Register Form -->
            <div id="register-form" class="hidden">
                <h2 class="text-3xl font-black text-white mb-8 border-b border-white/5 pb-4">Start Journey</h2>
                <form id="register-form-submit" class="space-y-6">
                    <div>
                        <label class="block text-gray-500 text-xs font-black uppercase tracking-widest mb-2 px-1">Full Name</label>
                        <input id="register-name" type="text" placeholder="John Doe" required
                            class="w-full px-6 py-4 bg-black/30 border border-white/5 rounded-2xl text-white placeholder-gray-700 focus:outline-none input-glow transition-all">
                    </div>
                    <div>
                        <label class="block text-gray-500 text-xs font-black uppercase tracking-widest mb-2 px-1">Email Address</label>
                        <input id="register-email" type="email" placeholder="john@example.com" required
                            class="w-full px-6 py-4 bg-black/30 border border-white/5 rounded-2xl text-white placeholder-gray-700 focus:outline-none input-glow transition-all">
                    </div>
                    <button type="submit" class="w-full py-5 bg-blue-600 hover:bg-blue-500 text-white font-black rounded-2xl transition-all shadow-xl shadow-blue-600/20 transform hover:-translate-y-1 active:scale-95 uppercase tracking-widest">
                        Get Started
                    </button>
                </form>
                <div id="register-google" style="display:none; margin-top:24px">
                    <div style="display:flex; align-items:center; gap:10px; color:#6B7280; font-size:11px; letter-spacing:0.18em; text-transform:uppercase; margin-bottom:14px">
                        <span style="flex:1; height:1px; background:rgba(255,255,255,0.08)"></span>
                        <span>Or</span>
                        <span style="flex:1; height:1px; background:rgba(255,255,255,0.08)"></span>
                    </div>
                    <div id="g-host-register" style="display:flex; justify-content:center"></div>
                </div>
                <p class="text-center mt-10 text-gray-600 text-sm">
                    Already a member? 
                    <button id="show-login" class="text-blue-400 hover:text-blue-300 font-black ml-1 uppercase text-xs tracking-widest">Log In</button>
                </p>
                <p id="register-error" class="mt-6 text-center text-red-400 hidden bg-red-400/10 py-4 rounded-2xl border border-red-400/20 text-sm font-bold"></p>
            </div>
        </div>
    </div>

    <!-- Premium Loader Overhaul -->
    <div id="loader" class="fixed inset-0 bg-[#0c0e12] flex flex-col items-center justify-center z-50 hidden transition-opacity duration-500">
        <div class="relative flex items-center justify-center">
            <div class="premium-loader"></div>
            <img src="/assets/logo.png" class="absolute w-12 h-12 object-contain animate-pulse">
        </div>
        <p class="mt-8 text-blue-400 font-black tracking-[0.3em] text-sm animate-pulse uppercase">Authenticating</p>
    </div>

        <script>
            // Register Service Worker
            if ('serviceWorker' in navigator) {
                window.addEventListener('load', () => {
                    navigator.serviceWorker.register('/sw.js')
                        .then(reg => console.log('SW Registered', reg))
                        .catch(err => console.log('SW Register Error', err));
                });
            }

            const loginForm = document.getElementById('login-form');
        const registerForm = document.getElementById('register-form');
        const loader = document.getElementById('loader');

        document.getElementById('show-register').onclick = () => {
            loginForm.classList.add('hidden');
            registerForm.classList.remove('hidden');
        };

        document.getElementById('show-login').onclick = () => {
            registerForm.classList.add('hidden');
            loginForm.classList.remove('hidden');
        };

        function showLoader(show) { loader.classList.toggle('hidden', !show); }

        document.getElementById('login-form-submit').onsubmit = async (e) => {
            e.preventDefault();
            showLoader(true);
            const name = document.getElementById('login-name').value;
            const email = document.getElementById('login-email').value;
            const error = document.getElementById('login-error');
            
            try {
                const res = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email })
                });
                const data = await res.json();
                if (data.success) window.location.href = '/home';
                else {
                    showLoader(false);
                    error.textContent = data.error;
                    error.classList.remove('hidden');
                }
            } catch {
                showLoader(false);
                error.textContent = "Connection error. Please try again.";
                error.classList.remove('hidden');
            }
        };

        document.getElementById('register-form-submit').onsubmit = async (e) => {
            e.preventDefault();
            showLoader(true);
            const name = document.getElementById('register-name').value;
            const email = document.getElementById('register-email').value;
            const error = document.getElementById('register-error');
            
            try {
                const res = await fetch('/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, email })
                });
                const data = await res.json();
                if (data.success) window.location.href = '/home';
                else {
                    showLoader(false);
                    error.textContent = data.error;
                    error.classList.remove('hidden');
                }
            } catch {
                showLoader(false);
                error.textContent = "Registration failed. Try again.";
                error.classList.remove('hidden');
            }
        };

        // ── Google Sign-In ──
        // Asks the server for the configured client ID, lazy-loads Google
        // Identity Services, and renders a button on both the sign-in and
        // sign-up panels. One Tap also fires for users already signed in
        // to Google in their browser.
        (async function setupGoogle() {
            try {
                const r = await fetch('/auth/google/config');
                const cfg = r.ok ? await r.json() : {};
                if (!cfg.enabled || !cfg.clientId) return;

                window.handleGoogleCredential = async (response) => {
                    showLoader(true);
                    try {
                        const res = await fetch('/auth/google', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'same-origin',
                            body: JSON.stringify({ credential: response.credential }),
                        });
                        const data = await res.json();
                        if (data.success) { window.location.href = '/home'; return; }
                        showLoader(false);
                        const err = document.getElementById('login-error');
                        if (err) {
                            err.textContent = data.error || 'Google sign-in failed.';
                            err.classList.remove('hidden');
                        }
                    } catch (e) {
                        showLoader(false);
                    }
                };

                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = 'https://accounts.google.com/gsi/client';
                    s.async = true; s.defer = true;
                    s.onload = resolve; s.onerror = reject;
                    document.head.appendChild(s);
                });

                google.accounts.id.initialize({
                    client_id: cfg.clientId,
                    callback: window.handleGoogleCredential,
                    auto_select: false,
                    use_fedcm_for_prompt: true,
                });

                const opts = { theme: 'filled_black', size: 'large', text: 'continue_with', shape: 'pill', logo_alignment: 'left', width: 320 };
                const loginHost = document.getElementById('g-host-login');
                const regHost = document.getElementById('g-host-register');
                if (loginHost) google.accounts.id.renderButton(loginHost, opts);
                if (regHost) google.accounts.id.renderButton(regHost, opts);
                document.getElementById('login-google').style.display = 'block';
                document.getElementById('register-google').style.display = 'block';

                google.accounts.id.prompt();
            } catch (e) {
                console.warn('Google sign-in unavailable:', e);
            }
        })();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
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
    if not os.path.exists('main.html'):
        return "Error: main.html not found in app directory. Place it here.", 500
    
    with open('main.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Inject API Key and Source URL for production compatibility
    api_key = os.environ.get('GEMINI_API_KEY', '')
    site_url = request.url_root.rstrip('/')
    
    injection = f"""
    <script>
        window.__gemini_api_key = "{api_key}";
        window.__asana_mind_url = "{site_url}";
    </script>
    """
    # Insert before the closing head tag or at the beginning of body
    if '</head>' in content:
        content = content.replace('</head>', f'{injection}</head>')
    else:
        content = injection + content
        
    return render_template_string(content)

@app.route('/profile')
def profile_page():
    if not session.get('logged_in'):
        return redirect(url_for('index'))
    if not os.path.exists('profile.html'):
        return "Error: profile.html not found in app directory. Place it here.", 500
        
    with open('profile.html', 'r', encoding='utf-8') as f:
        content = f.read()
        
    return render_template_string(content)


@app.route('/register', methods=['POST'])
def register():
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
        return jsonify({'success': False, 'error': 'Invalid Google token: ' + str(e)}), 401

    email = (info.get('email') or '').lower().strip()
    if not email or not info.get('email_verified'):
        return jsonify({'success': False, 'error': 'Google account email is not verified.'}), 401

    name = (info.get('name') or info.get('given_name') or email.split('@')[0]).strip()
    picture = info.get('picture', '')
    google_sub = info.get('sub')

    today = datetime.now().strftime('%Y-%m-%d')
    existing = users.find_one({'email': email})
    if existing:
        # Backfill google linkage and update activity log.
        users.update_one(
            {'email': email},
            {
                '$set': {'name': existing.get('name') or name, 'picture': picture, 'google_sub': google_sub},
                '$addToSet': {'activity_log': today},
            },
        )
        session_name = existing.get('name') or name
    else:
        users.insert_one({
            'name': name,
            'email': email,
            'picture': picture,
            'google_sub': google_sub,
            'auth_provider': 'google',
            'created_at': datetime.utcnow(),
            'activity_log': [today],
            'completed_asanas': {},
        })
        session_name = name

    session.permanent = True
    session['logged_in'] = True
    session['user_email'] = email
    session['user_name'] = session_name
    session['picture'] = picture
    return jsonify({'success': True, 'name': session_name, 'email': email})


@app.route('/auth/google/config', methods=['GET'])
def google_config():
    """Tells the frontend whether Google sign-in is configured and the client ID."""
    return jsonify({
        'enabled': bool(GOOGLE_AUTH_AVAILABLE and GOOGLE_CLIENT_ID),
        'clientId': GOOGLE_CLIENT_ID,
    })


def profile():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    email = session['user_email']
    user = users.find_one({'email': email})
    if user:
        # Sort activity_log for frontend
        activity_log = sorted(user.get('activity_log', []))
        total_active_days = len(activity_log)
        return jsonify({
            'name': user['name'],
            'email': user['email'],
            'created_at': user['created_at'].isoformat() if 'created_at' in user else None,
            'activity_log': activity_log,
            'completed_asanas': user.get('completed_asanas', {}),
            'total_active_days': total_active_days
        })
    return jsonify({'error': 'User not found'}), 404

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
    users.update_one(
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
    return redirect(url_for('index'))

# Serve PWA Static Assets (Manifest & Service Worker)
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('.', 'sw.js')

# Serve static assets
@app.route('/assets/<path:filename>')
def serve_asset(filename):
    try:
        return send_from_directory('assets', filename)
    except FileNotFoundError:
        return "Asset not found.", 404


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
    ctx_bits = []
    if ctx.get('screen'):
        ctx_bits.append(f"Screen: {ctx['screen']}")
    if ctx.get('pose'):
        pose_bit = ctx['pose']
        if ctx.get('poseSanskrit') and ctx['poseSanskrit'] != pose_bit:
            pose_bit = f"{pose_bit} ({ctx['poseSanskrit']})"
        if ctx.get('poseLevel'):
            pose_bit += f", {ctx['poseLevel']}"
        ctx_bits.append(f"Current pose: {pose_bit}")
    if ctx.get('score') is not None:
        ctx_bits.append(f"Alignment: {ctx['score']}%")
    if ctx.get('courseMode'):
        ctx_bits.append("In course test mode")
    if ctx.get('courseCompleted') is not None and ctx.get('courseTotal'):
        ctx_bits.append(f"Course progress: {ctx['courseCompleted']} of {ctx['courseTotal']} complete")
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
    email = session.get('email', '')
    try:
        db.users.update_one(
            {'email': email},
            {'$push': {'session_history': {'$each': sessions[-60:]}}},
            upsert=True
        )
        return jsonify({'success': True, 'synced': len(sessions)})
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
    if not db_connected or course_progress_col is None:
        return jsonify({'success': True, 'progress': None, 'note': 'DB offline'})
    email = session.get('user_email')
    doc = course_progress_col.find_one({'email': email})
    if not doc:
        return jsonify({'success': True, 'progress': None})
    doc.pop('_id', None)
    return jsonify({'success': True, 'progress': doc.get('progress'), 'updatedAt': doc.get('updatedAt')})


@app.route('/api/course-progress', methods=['PUT', 'POST'])
def save_course_progress():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not db_connected or course_progress_col is None:
        return jsonify({'success': True, 'note': 'DB offline'})
    data = request.get_json(silent=True) or {}
    progress = data.get('progress')
    if not progress:
        return jsonify({'success': False, 'error': 'Empty progress'}), 400
    email = session.get('user_email')
    course_progress_col.update_one(
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
    if streak_freeze_col is None:
        return None
    doc = streak_freeze_col.find_one({'email': email})
    if not doc:
        doc = {'email': email, 'usedWeeks': [], 'autoApplied': []}
        streak_freeze_col.insert_one(doc)
    return doc


@app.route('/api/streak', methods=['GET'])
def get_streak():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not db_connected:
        return jsonify({'success': True, 'streak': 0, 'best': 0, 'freezeAvailable': False})
    email = session.get('user_email')
    user = users.find_one({'email': email})
    activity = sorted(user.get('activity_log', [])) if user else []

    # Compute streak — number of consecutive days up to today, with freeze tokens
    # auto-applied to bridge a single missed day per ISO week.
    today = datetime.utcnow().date()
    freeze_doc = _ensure_streak_freezes_doc(email) if streak_freeze_col is not None else None
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
                if streak_freeze_col is not None:
                    streak_freeze_col.update_one(
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
    if not db_connected or streak_freeze_col is None:
        return jsonify({'success': False, 'error': 'DB offline'}), 500
    email = session.get('user_email')
    today = datetime.utcnow().date()
    wk = _iso_week_key(today)
    doc = _ensure_streak_freezes_doc(email)
    if wk in doc.get('usedWeeks', []):
        return jsonify({'success': False, 'error': 'Freeze already used this week'}), 400
    streak_freeze_col.update_one(
        {'email': email},
        {'$addToSet': {'usedWeeks': wk, 'autoApplied': today.isoformat()}},
    )
    # Add to activity_log so dashboard reflects it.
    users.update_one({'email': email}, {'$addToSet': {'activity_log': today.isoformat()}})
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

    if db_connected and certificates_col is not None:
        try:
            certificates_col.update_one(
                {'email': record['email'], 'courseId': record['courseId']},
                {'$setOnInsert': record},
                upsert=True,
            )
            existing = certificates_col.find_one({'email': record['email'], 'courseId': record['courseId']})
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
    if not db_connected or certificates_col is None:
        return jsonify({'success': True, 'certificates': []})
    docs = list(certificates_col.find({'email': session.get('user_email')}))
    out = []
    for d in docs:
        d.pop('_id', None)
        out.append(d)
    return jsonify({'success': True, 'certificates': out})


@app.route('/verify/<cert_id>')
def verify_certificate(cert_id):
    """Public verification page — anyone with the URL can confirm authenticity."""
    if not db_connected or certificates_col is None:
        return _verify_html(None, cert_id, 'database-offline')
    cert = certificates_col.find_one({'certId': (cert_id or '').upper()})
    if not cert:
        return _verify_html(None, cert_id, 'not-found')
    return _verify_html(cert, cert_id, 'ok')


def _verify_html(cert, requested_id, state):
    name = cert.get('userName') if cert else ''
    course = cert.get('courseTitle') if cert else ''
    score = cert.get('score') if cert else ''
    issued = cert.get('issuedAt') if cert else ''
    poses = cert.get('poses') or [] if cert else []
    is_master = cert.get('isMaster') if cert else False
    issued_str = ''
    if issued:
        try:
            issued_str = datetime.fromisoformat(issued).strftime('%d %b %Y')
        except Exception:
            issued_str = issued[:10]
    body_status = {
        'ok': 'verified',
        'not-found': 'not found',
        'database-offline': 'temporarily unavailable',
    }.get(state, 'unknown')

    rows_html = ''
    for r in poses:
        rows_html += f'<tr><td style="padding:8px 0;color:#14120E">{r.get("name","")}</td><td style="text-align:right;color:#0F3D2E;font-weight:600">{r.get("mark",0)}%</td></tr>'

    if state == 'ok':
        body = f"""
        <span class=\"kicker\" style=\"color:#0F3D2E\">Authentic ✓</span>
        <h1 style=\"font-family:Fraunces,serif;font-size:42px;font-weight:300;color:#14120E;margin:8px 0 0\">{name}</h1>
        <p style=\"color:#4A453B;margin:6px 0 18px\">{course} {'(Master Certificate)' if is_master else ''}</p>
        <div style=\"background:#0F3D2E;color:#F5F2EB;border-radius:18px;padding:20px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap\">
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Final mark</span><div style=\"font-family:Fraunces,serif;font-size:36px;font-weight:300;line-height:1\">{score}%</div></div>
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Issued</span><div style=\"font-family:Fraunces,serif;font-size:18px;line-height:1.3;margin-top:8px\">{issued_str}</div></div>
            <div><span class=\"kicker\" style=\"color:#E0A23F\">Cert id</span><div style=\"font-family:monospace;font-size:13px;margin-top:8px\">{cert.get('certId','')}</div></div>
        </div>
        {f'<table style="width:100%;margin-top:20px;border-collapse:collapse;font-size:14px"><tbody>{rows_html}</tbody></table>' if rows_html else ''}
        """
    else:
        body = f"""
        <span class=\"kicker\" style=\"color:#C2552F\">Not verifiable</span>
        <h1 style=\"font-family:Fraunces,serif;font-size:36px;font-weight:300;color:#14120E;margin:8px 0 0\">Certificate {body_status}</h1>
        <p style=\"color:#4A453B;margin:6px 0 0\">No certificate exists with id <code>{requested_id}</code>.</p>
        """

    return f"""<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>Verify Certificate · AsanMinds</title>
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<link rel=\"icon\" href=\"/assets/logo.png\">
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
            html_content=f"""<p>Dear {user_name},</p>
<p>Congratulations on completing <b>{course_title}</b> with a final mark of <b>{score}%</b>.</p>
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
        print(f'sendgrid error: {e}')
        return jsonify({'success': False, 'error': 'Email send failed; please use Download. (' + str(e)[:80] + ')'}), 500


# ─────────────────────────────────────────────────────────────
# USER PREFERENCES (items 33, 38, 39)
# Stays-signed-in flag, theme, daily reminder time, language.
# ─────────────────────────────────────────────────────────────

@app.route('/api/preferences', methods=['GET'])
def get_preferences():
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not db_connected or preferences_col is None:
        return jsonify({'success': True, 'preferences': {}})
    doc = preferences_col.find_one({'email': session.get('user_email')}) or {}
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
    if not db_connected or preferences_col is None:
        return jsonify({'success': True, 'note': 'DB offline'})
    preferences_col.update_one(
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
    if not db_connected or push_subs_col is None:
        return jsonify({'success': False, 'error': 'DB offline'}), 500
    data = request.get_json(silent=True) or {}
    sub = data.get('subscription')
    reminder_time = data.get('reminderTime') or '07:00'
    if not sub or 'endpoint' not in sub:
        return jsonify({'success': False, 'error': 'Invalid subscription'}), 400
    push_subs_col.update_one(
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
    if push_subs_col is not None:
        push_subs_col.delete_one({'email': session.get('user_email')})
    return jsonify({'success': True})


@app.route('/api/push/test', methods=['POST'])
def push_test():
    """Send a test notification to the current user. Returns success even when
    the push stack isn't installed — UI shows the right message."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not (PUSH_AVAILABLE and os.environ.get('VAPID_PRIVATE_KEY') and push_subs_col is not None):
        return jsonify({'success': False, 'error': 'Push not configured on server.'}), 503
    sub_doc = push_subs_col.find_one({'email': session.get('user_email')})
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
            users.delete_one({'email': email})
            for col in (certificates_col, course_progress_col, preferences_col,
                        push_subs_col, streak_freeze_col):
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
<link rel="icon" href="/assets/logo.png">
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


if __name__ == '__main__':
    # Use dynamic port for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')