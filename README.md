# SUNDAY - AI-Powered Yoga Wellness Platform

![SUNDAY Logo](assets/logo.png)

## 🧘 Overview

SUNDAY is an intelligent yoga wellness platform that combines voice interaction with real-time pose detection and correction. Using AI-powered computer vision and natural language processing, SUNDAY provides personalized yoga guidance, real-time posture feedback, and comprehensive progress tracking.

**Live Demo:** [https://asanamind.onrender.com](https://asanamind.onrender.com)

---

## ✨ Key Features

### 🎤 Voice Assistant ("Sunday")
- **Wake Word Activation**: Say "Sunday" to activate hands-free control
- **Natural Language Commands**: Control the platform using conversational language
- **Text-to-Speech Feedback**: Audible guidance and corrections during practice
- **Browser Automation**: Seamless navigation through voice commands

### 📹 Real-Time Pose Detection
- **TensorFlow.js Integration**: Client-side ML inference for privacy
- **MoveNet Model**: Fast and accurate pose estimation
- **Live Video Analysis**: Real-time skeleton overlay and feedback
- **Multi-Pose Support**: 7 yoga poses with detailed validation

### 🎯 AR Pose Correction System
- **20-Point Biomechanical Analysis** (Tadasana/Mountain Pose)
- **Priority-Based Feedback**: Critical to minor corrections ranked by importance
- **Color-Coded Guidance**: Red (critical), Yellow (refinement), Green (perfect)
- **Scoring System**: 0-100% accuracy with weighted penalties
- **Visual Feedback**: Skeleton overlay with highlighted correction areas

### 📊 Progress Tracking
- **Activity Dashboard**: Daily practice statistics and streaks
- **Performance Charts**: Pose completion distribution and trends
- **Achievement System**: Milestone rewards for consistent practice
- **365-Day Heatmap**: Visual representation of practice consistency
- **Ranking System**: Novice → Regular → Expert → Master progression

### 🌐 Progressive Web App (PWA)
- **Offline Support**: Service worker for offline functionality
- **Mobile Optimized**: Responsive design for all devices
- **Install Prompt**: Add to home screen capability
- **Cross-Platform**: Works on iOS, Android, and Desktop

---

## 🏗️ Architecture

### Frontend
- **HTML5/CSS3/JavaScript**: Vanilla JS for maximum performance
- **Tailwind CSS**: Utility-first styling with dark theme
- **TensorFlow.js**: Browser-based machine learning
- **Tone.js**: Audio synthesis for ambient sounds
- **WebRTC**: Camera access for pose detection

### Backend
- **Flask**: Python web framework (HTTP server)
- **MongoDB Atlas**: Cloud database for user data
- **Python Voice Assistant**: Separate process for voice control
- **Selenium WebDriver**: Browser automation for voice commands

### Machine Learning
- **MoveNet SinglePose Lightning**: Fast pose estimation model
- **Real-Time Inference**: 30 FPS pose detection
- **Client-Side Processing**: Privacy-first approach
- **Keypoint Detection**: 17-point body skeleton tracking

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Chrome Browser (for voice assistant)
- MongoDB Atlas account (for user authentication)
- Modern web browser with camera access

### Installation

1. **Clone the Repository**
```bash
git clone https://github.com/Majenayu/AsanaMind.git
cd AsanaMind
```

2. **Install Python Dependencies**
```bash
pip install -r requirements.txt
```

3. **Set Environment Variables**
Create a `.env` file in the root directory:
```env
MONGO_URI=your_mongodb_connection_string
SECRET_KEY=your_secret_key_for_sessions
GEMINI_API_KEY=your_gemini_api_key_optional
PORT=5000
```

4. **Run the Application**

**Option A: Web Server Only**
```bash
python app.py
```
Access at: `http://localhost:5000`

**Option B: With Voice Assistant**
```bash
# Terminal 1: Start web server
python app.py

# Terminal 2: Start voice assistant
python assistant.py
```

---

## 📱 Usage Guide

### Getting Started

1. **Registration/Login**
   - Open the application in your browser
   - Register with name and email
   - Login to access the dashboard

2. **Dashboard Navigation**
   - View your practice statistics
   - Check daily streaks and achievements
   - Access pose library and AR correction

3. **Voice Commands** (if assistant is running)
   - Say "Sunday" to activate
   - "Open pose library" - Browse available poses
   - "Start posture correction" - Begin AR analysis
   - "Show dashboard" - View statistics
   - "Logout" - Sign out

4. **AR Pose Correction**
   - Select a pose from the library
   - Click "Start AR Correction"
   - Allow camera access
   - Stand in frame and follow real-time feedback
   - Aim for 70%+ accuracy score

### Supported Yoga Poses

| Pose Name | Sanskrit | Difficulty | Key Focus |
|-----------|----------|------------|-----------|
| Mountain Pose | Tadasana | Beginner | Foundation, alignment |
| Tree Pose | Vrikshasana | Beginner | Balance, focus |
| Prayer Pose | Namastey | Beginner | Centering, breath |
| Downward Dog | Adho Mukha Svanasana | Intermediate | Strength, flexibility |
| Warrior III | Virabhadrasana III | Intermediate | Balance, core |
| Dancer Pose | Natarajasana | Advanced | Balance, backbend |
| Bound Angle | Baddha Konasana | Beginner | Hip opening |

---

## 🎯 Tadasana (Mountain Pose) - Enhanced Detection

### 20-Point Validation System

#### Foundation (Priority 1-3)
- ✅ Foot spacing (hip-width apart)
- ✅ Weight distribution (even on both feet)
- ✅ Foot parallel alignment

#### Legs (Priority 1-3)
- ✅ Quadriceps engagement
- ✅ Knee straightness (165-190°)
- ✅ Knee tracking over ankles
- ✅ Hyperextension prevention

#### Pelvis & Core (Priority 1-2)
- ✅ Hip level alignment
- ✅ Pelvic positioning
- ✅ Core engagement

#### Spine & Torso (Priority 1-3)
- ✅ Spinal alignment (shoulders over hips)
- ✅ Chest opening
- ✅ Rib cage positioning

#### Shoulders (Priority 2-3)
- ✅ Shoulder level and relaxation
- ✅ Shoulder blade engagement
- ✅ Collarbone broadening

#### Arms (Priority 3-4)
- ✅ Natural arm positioning
- ✅ Energy flow through fingertips
- ✅ Hand placement by sides
- ✅ Arm symmetry

#### Head & Neck (Priority 1-3)
- ✅ Head alignment over shoulders
- ✅ Neck length and crown reach
- ✅ Jaw relaxation

#### Overall Alignment (Priority 1)
- ✅ Full body line assessment
- ✅ Energetic alignment

### Scoring System
- **90-100%**: Perfect alignment - Hold and breathe
- **75-89%**: Excellent - Minor refinements needed
- **60-74%**: Good - Focus on key adjustments
- **Below 60%**: Needs work - Address critical issues

---

## 🛠️ Technical Details

### Project Structure
```
AsanaMind/
├── app.py                      # Flask web server
├── assistant.py                # Voice assistant with Selenium
├── main.py                     # Alternative server implementation
├── index.html                  # Login/registration page
├── main.html                   # Main application (2862 lines)
├── profile.html                # User profile & analytics
├── sw.js                       # Service Worker for PWA
├── manifest.json               # PWA manifest
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project metadata
├── Procfile                    # Render deployment config
├── runtime.txt                 # Python version
├── README.md                   # This file
├── requirements.md             # Functional requirements
├── design.md                   # System design document
├── replit.md                   # Technical documentation
├── project_chart.md            # Project overview
├── assets/
│   ├── logo.png               # Application logo
│   └── poses/                 # Reference pose images
│       ├── tadasana.jpg
│       ├── vrikshasana.jpg
│       └── namaste.png
└── [Runtime files]
    ├── asana_status.json      # Assistant status
    ├── sunday_status.json     # Voice assistant state
    └── conversation_log.txt   # Voice interaction logs
```

### Dependencies

**Python Backend:**
```
Flask==3.0.0
pymongo==4.6.0
gunicorn==21.2.0
python-dotenv==1.0.0
speech_recognition==3.10.0
pyttsx3==2.90
selenium==4.15.0
```

**Frontend Libraries (CDN):**
- TensorFlow.js 3.13.0
- TensorFlow Models (Pose Detection) 2.0.0
- Tailwind CSS (latest)
- Tone.js 14.8.49
- Chart.js (for profile analytics)

### API Endpoints

**Authentication:**
- `POST /register` - User registration
- `POST /login` - User login
- `GET /logout` - User logout

**User Data:**
- `GET /api/user` - Get current user info
- `POST /api/complete-pose` - Log pose completion
- `GET /api/activity-data` - Get user activity history

**Static Files:**
- `GET /` - Login page
- `GET /home` - Main application
- `GET /profile` - User profile
- `GET /assets/<path>` - Static assets

### Database Schema

**Users Collection:**
```javascript
{
  _id: ObjectId,
  name: String,
  email: String (unique),
  password: String (hashed),
  created_at: Date,
  last_login: Date
}
```

**Activities Collection:**
```javascript
{
  _id: ObjectId,
  user_id: ObjectId,
  pose_name: String,
  score: Number,
  duration: Number,
  timestamp: Date
}
```

---

## 🔧 Configuration

### Voice Assistant Configuration

Edit `assistant.py` to customize:

```python
# Wake word
self.wake_word = "sunday"

# Base URL (change for production)
self.base_url = "http://127.0.0.1:5000"

# Speech recognition sensitivity
self.recognizer.energy_threshold = 800
self.recognizer.pause_threshold = 0.5
```

### Pose Detection Configuration

Edit `main.html` to customize:

```javascript
// Minimum confidence threshold
const MIN_CONFIDENCE = 0.3;

// Feedback stabilization (frames)
const BUFFER_SIZE = 15;

// Score history length (frames)
scoreHistory.length = 30; // ~1 second at 30fps

// Milestone requirements
if (poseScore >= 70 && milestonesEarned < 2) {
    highAccuracyTimer++; // 10 seconds = 300 frames
}
```

---

## 🚢 Deployment

### Render Deployment

1. **Connect GitHub Repository**
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Create new Web Service
   - Connect to `Majenayu/AsanaMind` repository

2. **Configure Build Settings**
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Environment**: Python 3

3. **Set Environment Variables**
   - `MONGO_URI`: Your MongoDB connection string
   - `SECRET_KEY`: Random secret key for sessions
   - `GEMINI_API_KEY`: (Optional) For AI assistant
   - `PORT`: 10000 (Render default)

4. **Deploy**
   - Click "Create Web Service"
   - Wait for deployment to complete
   - Access your app at the provided URL

### Local Development

```bash
# Development mode with auto-reload
export FLASK_ENV=development
python app.py

# Production mode
gunicorn app:app --bind 0.0.0.0:5000
```

---

## 🎨 Customization

### Changing Theme Colors

Edit `main.html` Tailwind config:

```javascript
tailwind.config = {
    theme: {
        extend: {
            colors: {
                'primary': '#42A5F5',      // Main blue
                'secondary': '#1976D2',    // Dark blue
                'accent': '#FFEB3B',       // Yellow/gold
                'background': '#121212',   // Dark background
                'card': '#1E1E1E',        // Card background
            }
        }
    }
}
```

### Adding New Poses

1. **Add pose image** to `assets/poses/`
2. **Update pose library** in `main.html`:

```javascript
{
    name: 'Your Pose Name',
    sanskrit: 'Sanskrit Name',
    difficulty: 'Beginner/Intermediate/Advanced',
    description: 'Pose description',
    benefits: ['Benefit 1', 'Benefit 2'],
    image: '/assets/poses/your-pose.jpg'
}
```

3. **Add validation logic** in `checkPose()` function:

```javascript
else if (poseName === 'Your Pose Name') {
    // Add your validation logic here
    // Check angles, positions, alignment
    // Push corrections to corrections array
}
```

---

## 🧪 Training Custom Models

### Option 1: TensorFlow.js Custom Model

1. **Collect Training Data**
   - Record videos of correct poses
   - Extract keypoints using MoveNet
   - Label data with pose names

2. **Train Model**
```python
import tensorflow as tf

# Create model
model = tf.keras.Sequential([
    tf.keras.layers.Dense(128, activation='relu'),
    tf.keras.layers.Dropout(0.2),
    tf.keras.layers.Dense(num_poses, activation='softmax')
])

# Train on keypoint data
model.fit(keypoints_data, labels, epochs=50)

# Convert to TensorFlow.js
import tensorflowjs as tfjs
tfjs.converters.save_keras_model(model, 'model/')
```

3. **Integrate with Website**
```javascript
// Load custom model
const customModel = await tf.loadLayersModel('/model/model.json');

// Use for classification
const prediction = customModel.predict(keypointsTensor);
```

### Option 2: Custom Pose Estimation Model

1. **Use MediaPipe or OpenPose** for training
2. **Export to ONNX format**
3. **Convert to TensorFlow.js**
4. **Replace MoveNet** in `main.html`

---

## 🐛 Troubleshooting

### Camera Not Working
- **Check permissions**: Allow camera access in browser settings
- **HTTPS required**: Camera API requires secure context
- **Try different browser**: Chrome/Edge recommended

### Voice Assistant Not Responding
- **Check microphone**: Ensure microphone is connected and working
- **Adjust sensitivity**: Modify `energy_threshold` in `assistant.py`
- **Check ChromeDriver**: Ensure ChromeDriver matches Chrome version

### MongoDB Connection Failed
- **Check URI**: Verify `MONGO_URI` in environment variables
- **Network access**: Whitelist IP in MongoDB Atlas
- **Database name**: Ensure database exists

### Low Pose Detection Accuracy
- **Lighting**: Ensure good lighting conditions
- **Distance**: Stand 6-8 feet from camera
- **Full body visible**: Ensure entire body is in frame
- **Camera angle**: Position camera at chest height

---

## 📊 Performance Optimization

### Frontend Optimization
- **Lazy loading**: Images loaded on demand
- **Service Worker**: Caches static assets
- **Debounced updates**: Reduces unnecessary re-renders
- **Client-side ML**: No server round-trips

### Backend Optimization
- **Connection pooling**: MongoDB connection reuse
- **Session management**: Efficient session storage
- **Gunicorn workers**: Multiple worker processes
- **Static file serving**: CDN for libraries

---

## 🔒 Security

### Best Practices Implemented
- ✅ Password hashing (not stored in plain text)
- ✅ Session management with secure cookies
- ✅ HTTPS enforcement in production
- ✅ Input validation and sanitization
- ✅ CORS configuration
- ✅ Environment variable protection

### Recommendations
- Use strong `SECRET_KEY` in production
- Enable MongoDB authentication
- Implement rate limiting for API endpoints
- Add CAPTCHA for registration
- Regular security audits

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. **Fork the repository**
2. **Create feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit changes**: `git commit -m 'Add amazing feature'`
4. **Push to branch**: `git push origin feature/amazing-feature`
5. **Open Pull Request**

### Development Guidelines
- Follow PEP 8 for Python code
- Use meaningful variable names
- Add comments for complex logic
- Test on multiple devices
- Update documentation

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👥 Authors

- **Majenayu** - *Initial work* - [GitHub](https://github.com/Majenayu)

---

## 🙏 Acknowledgments

- **TensorFlow.js Team** - For pose detection models
- **Google MoveNet** - For fast pose estimation
- **MongoDB Atlas** - For cloud database
- **Render** - For hosting platform
- **Tailwind CSS** - For styling framework
- **Yoga Community** - For pose guidance and validation

---

## 📞 Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/Majenayu/AsanaMind/issues)
- **Email**: Contact through GitHub profile
- **Documentation**: See `replit.md` and `design.md` for technical details

---

## 🗺️ Roadmap

### Upcoming Features
- [ ] More yoga poses (target: 20+ poses)
- [ ] Custom workout routines
- [ ] Social features (share progress)
- [ ] Meditation timer
- [ ] Breathing exercises
- [ ] Multi-language support
- [ ] Wearable device integration
- [ ] Offline mode improvements
- [ ] Video tutorials
- [ ] Community challenges

---

## 📈 Project Stats

- **Lines of Code**: ~5,000+
- **Supported Poses**: 7
- **Detection Points**: 17 keypoints
- **Accuracy**: 85%+ for Tadasana
- **Performance**: 30 FPS pose detection
- **Mobile Support**: iOS, Android, Desktop

---

**Made with ❤️ for the yoga community**

*Namaste* 🙏
`