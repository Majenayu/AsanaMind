from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session, send_from_directory
import pymongo
from datetime import datetime, timedelta
from collections import defaultdict
import os

app = Flask(__name__)
# Use environment variable for secret key, fallback ONLY for local dev
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-this-in-render')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# MongoDB connection
db_connected = False
# Priority: ENV variable for Render/Production
mongodb_uri = os.environ.get('MONGO_URI', "mongodb+srv://anv:anv@anv.thrp6za.mongodb.net/?appName=anv")

try:
    client = pymongo.MongoClient(mongodb_uri)
    # Ensure the correct database name is used
    db = client.get_database("face_auth")
    users = db.users
    client.admin.command('ping')
    print("✓ MongoDB connected successfully")
    db_connected = True
except Exception as e:
    print(f"✗ MongoDB connection failed: {e}")
    print("App will run without DB (profile features disabled)")

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
    
    session['logged_in'] = True
    session['user_email'] = email
    session['user_name'] = name
    return jsonify({'success': True})

@app.route('/api/profile')
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

if __name__ == '__main__':
    # Use dynamic port for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')