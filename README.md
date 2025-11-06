# 🧠 SUNDAY — AI Yoga Voice Assistant

A comprehensive AI-powered yoga wellness platform that combines voice interaction, real-time pose detection, and AR-based posture correction for an immersive yoga practice experience.

## 💬 Overview

**SUNDAY** is an intelligent voice assistant designed to help users interact with a yoga web application through natural voice commands. It seamlessly combines speech recognition, text-to-speech, and web automation to create an interactive, hands-free yoga assistant experience.

---

## ⚙️ How It Works

### 1. **Voice Activation**
The assistant continuously listens through your microphone for the wake word **"Sunday"** — allowing completely hands-free operation during your yoga practice.

### 2. **Speech Recognition**
When it hears "Sunday," the assistant activates and listens for your next command, such as:
- "Sunday, open pose library"
- "Sunday, start posture correction"
- "Sunday, show my routine"

This uses the `speech_recognition` module and Google's Speech API to convert your speech to text with high accuracy.

### 3. **AI Understanding & Navigation**
Once it recognizes your command, Sunday intelligently decides what to do:
- **Navigate** to different sections of the yoga web app (dashboard, asana library, AR correction, virtual assistant)
- **Guide** you through specific yoga poses (Tadasana, Vrikshasana, Namastey)
- **Provide spoken feedback** and pose descriptions using natural speech

### 4. **Text-to-Speech (TTS)**
Sunday talks back to you using `pyttsx3` for offline text-to-speech, providing:
- Natural voice acknowledgements ("Sure thing!", "I'm on it!")
- Detailed pose instructions and corrections
- Real-time feedback during your practice

### 5. **Web Integration with Selenium**
The assistant automatically opens and controls your local yoga interface using **Selenium with Chrome**, allowing voice commands to seamlessly interact with the web-based platform.

### 6. **Logging & Status Tracking**
- Every conversation is saved in `conversation_log.txt` for review
- System status (listening, speaking, processing) is tracked in `sunday_status.json`
- Full transparency into assistant behavior and command history

---

## 💻 Tech Stack

### **Python Libraries:**
- `speech_recognition` – For voice input and wake word detection
- `pyttsx3` – For offline text-to-speech output
- `selenium` – For controlling and automating the browser
- `pyaudio` – For microphone input handling
- `threading`, `json`, `os`, `time` – For system control and background tasks

### **Frontend Technologies:**
- **TensorFlow.js** – Real-time pose detection in the browser
- **MoveNet** – Lightweight pose estimation model
- **Tailwind CSS** – Modern dark-themed UI
- **Tone.js** – Audio synthesis for ambient sounds

### **Browser Automation:**
- Chrome WebDriver for seamless web control

### **Platform:**
- Works on Replit (with limited mic access) or locally on Windows/Linux
- Requires Python 3.x, Chrome browser, microphone, and webcam

---

## 🧘 Example Voice Commands

Once Sunday is running, you can say:

| Command | Action |
|---------|--------|
| **"Sunday, open the pose library"** | Opens the asana library with all available poses |
| **"Sunday, guide me through Tree Pose"** | Starts AR correction for Vrikshasana |
| **"Sunday, start posture correction"** | Activates camera-based AR pose correction |
| **"Sunday, show my routine"** | Opens your personalized daily yoga sequence |
| **"Sunday, go to dashboard"** | Returns to the home screen |
| **"Sunday, open assistant"** | Activates the AI chat for yoga questions |
| **"Sunday, thank you"** | Friendly acknowledgement |
| **"Sunday, stop"** | Shuts down the assistant gracefully |

---

## 🗂️ Project Files

| File | Description |
|------|-------------|
| `assistant.py` | Core voice assistant logic with wake word detection |
| `server.py` | Simple HTTP server for the web interface |
| `index.html` | Complete yoga web platform with AR correction |
| `conversation_log.txt` | Stores all spoken interactions |
| `sunday_status.json` | Tracks system state and current command |
| `assets/poses/` | Reference images for yoga poses |

---

## 🚀 Getting Started

### **Running the Server:**
The web interface runs automatically via the configured workflow:
```bash
python server.py
```
This starts the server on `http://0.0.0.0:5000`

**The server must be running before starting the voice assistant.**

### **Running the Voice Assistant:**
To activate Sunday's voice control (requires the server to be running):
```bash
python assistant.py
```

The assistant will:
1. Connect to the yoga platform at `http://127.0.0.1:5000`
2. Calibrate your microphone
3. Open Chrome with the yoga platform
4. Start listening for the wake word "Sunday"
5. Respond to your voice commands

**Prerequisites:**
- The HTTP server must be running on port 5000 (`python server.py`)
- Microphone permissions
- Chrome browser installed
- Active internet connection for speech recognition

---

## 🧩 What Makes It Special

✨ **Fully Offline TTS** – Works without internet for speech output  
🎯 **Smart Wake Word Detection** – Only activates when you say "Sunday"  
🗣️ **Natural Language Understanding** – Flexible command mapping with keyword recognition  
🤖 **Real-Time Browser Control** – Seamlessly blends AI and automation  
📊 **AR Pose Correction** – Live camera-based feedback with scoring system  
💪 **3 Core Poses** – Tadasana, Vrikshasana, and Namastey with detailed validation  
🌙 **Dark Theme UI** – Calming interface perfect for yoga sessions  
📈 **Progress Tracking** – Dashboard with streak counter and wellness metrics  

---

## 🎨 Platform Features

### **Dashboard**
- Daily yoga progress tracking
- Posture accuracy score
- Streak counter and calories burned
- Personalized insights

### **Asana Library**
- Complete pose database
- Sanskrit names and benefits
- Precautions and targeted muscle groups
- Reference images for each pose

### **AR Correction**
- Real-time camera-based pose analysis
- Color-coded skeleton overlay (green = correct, red = needs work)
- Live scoring system (0-100%)
- Specific correction suggestions
- Side-by-side reference pose display

### **Virtual Assistant**
- Gemini 2.5 Flash AI integration
- Ask yoga and wellness questions
- Get real-time advice with sources
- Markdown-formatted responses

### **Routine Builder**
- Personalized daily sequences
- Wellness tracking (sleep, stress, hydration)
- Meal recommendations

---

## 🎤 Voice Control Options

The platform supports **two voice control methods**:

1. **Python Voice Assistant (assistant.py)** – Advanced
   - Wake word activation ("Sunday")
   - Offline TTS responses
   - Full browser automation
   - Conversation logging

2. **Browser Speech Recognition** – Simple
   - Click the microphone button in the web UI
   - Direct voice commands without wake word
   - Works entirely in the browser
   - No additional setup required

---

## 📝 Development Notes

- The assistant uses **energy threshold** adjustment for ambient noise handling
- **Dynamic energy threshold** adapts to your environment
- **Pause threshold** of 1.0 seconds allows natural speech patterns
- Chrome runs in automation mode with camera permissions pre-granted
- All pose detection happens **client-side** for privacy and speed

---

## 🔒 Privacy & Security

- All video processing happens locally in your browser
- Camera feed never leaves your device
- Voice recognition uses Google's API but no data is stored
- Conversation logs are stored locally only

---

## 🛠️ Troubleshooting

**Assistant won't start:**
- Check microphone permissions
- Ensure Chrome is installed
- Verify internet connection for speech recognition

**Voice commands not recognized:**
- Speak clearly after saying "Sunday"
- Check microphone calibration in logs
- Ensure ambient noise is not too high

**Camera not working:**
- Grant camera permissions in browser
- Try refreshing the page
- Check if camera is being used by another app

---

## 📚 Learn More

This project demonstrates the integration of:
- Voice-controlled interfaces
- Real-time ML in browsers
- Browser automation with Selenium
- Modern web UI with Tailwind CSS
- Offline-first design principles

Perfect for understanding how to build accessible, voice-first applications!

---

**Namaste!** 🙏

Built with ❤️ for yogis everywhere
