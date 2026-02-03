import speech_recognition as sr
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import os
import threading
import json
import pyttsx3
import random
import subprocess
import queue
import pythoncom  # Added for COM threading

# Set to your ChromeDriver path if not in PATH; '' if in PATH
CHROMEDRIVER_PATH = '' 

class AIVoiceAssistant:
    def __init__(self):
        self.status_file = "sunday_status.json"
        self.conv_log_file = "conversation_log.txt"
        self.listening = True
        self.wake_word = "sunday"
        
        # Speech Queue Setup (SAPI/COM version)
        self.speech_queue = queue.Queue()
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()
        
        self.log_conversation("System", "Sunday AI starting with synchronized SAPI Voice")

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        # Sensitivity tuning
        self.recognizer.energy_threshold = 800  # More sensitive
        self.recognizer.pause_threshold = 0.5    # Snappier
        self.recognizer.dynamic_energy_threshold = True
        
        self.calibrate_microphone()

        self.chrome_options = Options()
        self.chrome_options.add_argument("--use-fake-ui-for-media-stream")
        self.chrome_options.add_argument("--disable-web-security")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_argument("--window-size=1280,960")
        
        self.driver = None
        threading.Thread(target=self.open_browser, daemon=True).start()

        time.sleep(1)
        threading.Thread(target=self.listen_loop, daemon=True).start()

        self.speak("Hello! I am Sunday. I am initialized and ready to manage your yoga platform. Say my name to begin!")

    def _speech_worker(self):
        """Dedicated thread to handle TTS sequentially using Windows SAPI."""
        pythoncom.CoInitialize()
        print("🔊 Speech worker initialized")
        
        while self.listening:
            try:
                text = self.speech_queue.get(timeout=1)
                if not text: continue
                
                print(f"📣 SPEAKING: {text}")
                # Update UI to Talking
                self.update_ui('talking')
                
                success = False
                if os.name == 'nt':
                    try:
                        import win32com.client
                        voice = win32com.client.Dispatch("SAPI.SpVoice")
                        voice.Rate = 1
                        voice.Speak(text)
                        success = True
                    except: pass
                
                if not success:
                    try:
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.say(text)
                        engine.runAndWait()
                    except: pass
                
                # Update UI back to Idle
                self.update_ui('idle')
                self.speech_queue.task_done()
            except queue.Empty: continue
            except: pass

    def speak(self, text):
        if not text: return False
        self.speech_queue.put(text)
        return True

    def update_ui(self, state):
        """Update the frontend mic status via Selenium"""
        if self.driver:
            try:
                self.driver.execute_script(f"if(window.app && window.app.updateVoiceStatus) {{ window.app.updateVoiceStatus('{state}'); }}")
            except: pass

    def open_browser(self):
        server_url = "http://127.0.0.1:5000/home"
        try:
            self.driver = webdriver.Chrome(options=self.chrome_options)
            self.driver.get(server_url)
            self.update_ui('idle')
        except: pass

    def log_conversation(self, speaker, message):
        timestamp = time.strftime("%H:%M:%S")
        with open(self.conv_log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {speaker}: {message}\n")
        print(f"[{timestamp}] {speaker}: {message}")

    def calibrate_microphone(self):
        try:
            print("👂 Calibrating mic...")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            print("✅ Mic ready.")
        except: pass

    def select_pose(self, pose_key):
        if not self.driver: return False
        try:
            pose_map = {
                'tadasana': 'Tadasana', 'mountain': 'Tadasana',
                'vrikshasana': 'Vrikshasana', 'tree': 'Vrikshasana',
                'namastey': 'Namastey', 'prayer': 'Namastey',
                'dog': 'Adho Mukha Svanasana', 'downward': 'Adho Mukha Svanasana',
                'warrior': 'Virabhadrasana III', 'warrior three': 'Virabhadrasana III',
                'dancer': 'Natarajasana', 'natarajasana': 'Natarajasana',
                'bound': 'Baddha Konasana', 'butterfly': 'Baddha Konasana'
            }
            exact_name = pose_map.get(pose_key.lower(), pose_key)
            self.navigate_section('ar_correction')
            time.sleep(0.5)
            self.driver.execute_script(f"if(window.app && window.app.selectAsanaAndStart) {{ window.app.selectAsanaAndStart('{exact_name}'); }}")
            return True
        except: return False

    def listen_for_speech(self, t, l):
        try:
            with self.microphone as s: return self.recognizer.listen(s, timeout=t, phrase_time_limit=l)
        except: return None

    def recognize_audio(self, audio):
        try:
            return self.recognizer.recognize_google(audio).lower().strip()
        except: return None

    def navigate_section(self, section):
        if not self.driver: return False
        try:
            section_map = {
                'home': 'dashboard', 'dashboard': 'dashboard',
                'library': 'asana', 'asana': 'asana', 'poses': 'asana',
                'ar_correction': 'ar_correction', 'ar': 'ar_correction', 'camera': 'ar_correction',
                'course': 'course', 'test': 'course',
                'assistant': 'assistant', 'chat': 'assistant'
            }
            target = section_map.get(section, section)
            self.speak(f"Opening {target}")
            self.driver.execute_script(f"if(window.app) {{ window.app.navigate('{target}'); }}")
            return True
        except: return False

    def process_command(self, cmd):
        # FAST NORMALIZATION
        cmd = cmd.replace("libary", "library").replace("post", "pose")
        
        # 1. CORE NAVIGATION
        if 'home' in cmd or 'dash' in cmd: self.navigate_section('dashboard')
        elif 'library' in cmd or 'asana' in cmd: self.navigate_section('asana')
        elif 'camera' in cmd or 'ar' in cmd: self.navigate_section('ar_correction')
        elif 'course' in cmd or 'test' in cmd: self.navigate_section('course')
        elif 'profile' in cmd: 
            self.speak("Profile")
            self.driver.get("http://127.0.0.1:5000/profile")

        # 2. POSES (ALL 7)
        elif 'tadasana' in cmd or 'mountain' in cmd: self.select_pose('Tadasana'); self.speak("Tadasana")
        elif 'vriksh' in cmd or 'tree' in cmd: self.select_pose('Vrikshasana'); self.speak("Tree Pose")
        elif 'namaste' in cmd or 'prayer' in cmd: self.select_pose('Namastey'); self.speak("Namastey")
        elif 'dog' in cmd: self.select_pose('Adho Mukha Svanasana'); self.speak("Downward Dog")
        elif 'warrior' in cmd: self.select_pose('Virabhadrasana III'); self.speak("Warrior Three")
        elif 'dancer' in cmd: self.select_pose('Natarajasana'); self.speak("Dancer")
        elif 'bound' in cmd or 'butterfly' in cmd: self.select_pose('Baddha Konasana'); self.speak("Bound Angle")

        # 3. ADVANCED BROWSER CONTROL
        elif 'top' in cmd: self.driver.execute_script("window.scrollTo(0, 0)"); self.speak("Top")
        elif 'bottom' in cmd: self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)"); self.speak("Bottom")
        elif 'scroll down' in cmd: self.driver.execute_script("window.scrollBy(0, 500)"); self.speak("Down")
        elif 'scroll up' in cmd: self.driver.execute_script("window.scrollBy(0, -500)"); self.speak("Up")
        elif 'mute' in cmd or 'silent' in cmd: self.driver.execute_script("const v = document.querySelector('video'); if(v) v.muted = true;"); self.speak("Muted")
        elif 'unmute' in cmd or 'sound' in cmd: self.driver.execute_script("const v = document.querySelector('video'); if(v) v.muted = false;"); self.speak("Sound on")
        elif 'refresh' in cmd or 'reload' in cmd: self.driver.refresh(); self.speak("Reset")
        elif 'logout' in cmd: self.driver.get("http://127.0.0.1:5000/logout"); self.speak("Out")
        elif 'back' in cmd: self.driver.back(); self.speak("Back")
        
        # 4. UTILS
        elif 'status' in cmd or 'ready' in cmd: self.speak("Ready")
        elif 'recalibrate' in cmd: self.calibrate_microphone(); self.speak("Tuned")
        elif 'stop' in cmd or 'goodbye' in cmd: self.speak("Bye"); self.stop()
        else: self.speak("?")

    def listen_loop(self):
        print("🎤 SUNDAY LISTENING LOOP ACTIVE")
        while self.listening:
            try:
                # Listen for Wait word
                audio = self.listen_for_speech(3, 6)
                if audio:
                    print("👂 Ambient sound detected, recognizing...")
                    text = self.recognize_audio(audio)
                    if text:
                        print(f"📄 Text: {text}")
                        if self.wake_word in text:
                            print("✨ WAKE WORD DETECTED")
                            self.update_ui('listening')
                            self.speak("Listening")
                            
                            # Listen for Command
                            cmd_audio = self.listen_for_speech(5, 10)
                            if cmd_audio:
                                print("👂 Command sound detected...")
                                cmd_text = self.recognize_audio(cmd_audio)
                                if cmd_text:
                                    print(f"🎮 CMD: {cmd_text}")
                                    self.process_command(cmd_text)
                                else:
                                    print("❓ Command not recognized")
                            else:
                                print("⏰ Command timeout")
                            self.update_ui('idle')
                else:
                    # Low frequency heartbeat
                    if random.random() < 0.05: print("...waiting for 'Sunday'...")
            except Exception as e:
                print(f"⚠️ Listen Loop Error: {e}")
                time.sleep(1)

    def stop(self):
        self.listening = False
        if self.driver: 
            try: self.driver.quit()
            except: pass
        os._exit(0)

if __name__ == "__main__":
    assistant = AIVoiceAssistant()
    while assistant.listening: time.sleep(1)
