import speech_recognition as sr
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import threading
import json
import pyttsx3
import random
import subprocess
import sys

class AIVoiceAssistant:
    def __init__(self):
        self.status_file = "sunday_status.json"
        self.conv_log_file = "conversation_log.txt"
        self.listening = True
        self.wake_word = "sunday"
        self.failed_recognitions = 0
        
        self.setup_tts()
        self.log_conversation("System", "Sunday AI starting with simple TTS system")

        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        self.recognizer.energy_threshold = 3000
        self.recognizer.pause_threshold = 1.0
        self.recognizer.dynamic_energy_threshold = True
        
        self.calibrate_microphone()

        self.chrome_options = Options()
        self.chrome_options.add_argument("--use-fake-ui-for-media-stream")
        self.chrome_options.add_argument("--disable-web-security")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_argument("--window-size=1200,800")
        
        self.driver = None

        browser_thread = threading.Thread(target=self.open_browser, daemon=True)
        browser_thread.start()

        time.sleep(3)
        listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        listen_thread.start()

        self.write_status('ready', '', '')
        self.speak("I'm listening for you. Just say 'Sunday' when you need me!")
        self.speak("Hello! I'm Sunday, your yoga assistant. I'm here and ready to help you with your wellness journey. Just say 'Sunday' followed by what you'd like to do!")

    def setup_tts(self):
        try:
            self.tts_engine = pyttsx3.init()
            self.tts_engine.setProperty('rate', 150)
            self.tts_engine.setProperty('volume', 1.0)
            self.log_conversation("System", "TTS configured")
        except Exception as e:
            self.log_conversation("System", f"TTS setup error: {e}")
            self.tts_engine = None

    def speak(self, text):
        if not text or not self.listening:
            return False
            
        self.log_conversation("AI", text)
        self.write_status('speaking', '', text)
        
        try:
            if self.tts_engine:
                def speak_thread():
                    try:
                        engine = pyttsx3.init()
                        engine.setProperty('rate', 150)
                        engine.setProperty('volume', 1.0)
                        engine.say(text)
                        engine.runAndWait()
                    except Exception as e:
                        print(f"TTS Error: {e}")
                
                thread = threading.Thread(target=speak_thread, daemon=True)
                thread.start()
                return True
            else:
                print(f"🔊 AI: {text}")
                return False
                
        except Exception as e:
            self.log_conversation("System", f"Speak error: {e}")
            print(f"🔊 AI: {text}")
            return False

    def calibrate_microphone(self):
        try:
            self.log_conversation("System", "Calibrating microphone... Please wait.")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=3)
            self.log_conversation("System", "Microphone calibrated successfully")
        except Exception as e:
            self.log_conversation("System", f"Microphone calibration failed: {e}")

    def log_conversation(self, speaker, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {speaker}: {message}\n"
        with open(self.conv_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(log_entry.strip())

    def write_status(self, action, user_command='', ai_response=''):
        try:
            data = {
                'action': action,
                'timestamp': time.time(),
                'user_command': user_command,
                'ai_response': ai_response
            }
            with open(self.status_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.log_conversation("System", f"Status write error: {e}")

    def get_acknowledgement(self):
        acknowledgements = [
            "Sure thing!",
            "I'm on it!",
            "Right away!",
            "Absolutely!",
            "Got it!",
            "Okay!",
            "No problem!",
        ]
        return random.choice(acknowledgements)

    def open_browser(self):
        max_retries = 3
        server_url = "http://127.0.0.1:5000"
        
        for attempt in range(max_retries):
            try:
                self.driver = webdriver.Chrome(options=self.chrome_options)
                self.driver.get(server_url)
                
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                time.sleep(4)
                
                self.log_conversation("System", f"Browser connected to {server_url} on attempt {attempt + 1}")
                self.speak("Perfect! I'm all connected and ready to help you with your yoga practice.")
                return
                
            except Exception as e:
                self.log_conversation("System", f"Browser error attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    self.log_conversation("System", f"Retrying connection to server at {server_url}...")
                    time.sleep(2)
                else:
                    self.speak("Having trouble connecting to the yoga platform. Please make sure the server is running on port 5000.")

    def listen_for_speech(self, timeout=8, phrase_time_limit=10):
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            return audio
        except sr.WaitTimeoutError:
            return None
        except Exception as e:
            self.log_conversation("System", f"Listen error: {e}")
            return None

    def recognize_audio(self, audio):
        if not audio:
            return None
            
        try:
            text = self.recognizer.recognize_google(audio, language="en-US").lower().strip()
            if len(text) > 1:
                self.log_conversation("System", f"Recognized: {text}")
                self.failed_recognitions = 0
                return text
            return None
        except sr.UnknownValueError:
            self.log_conversation("System", "Speech recognition could not understand audio")
            self.failed_recognitions += 1
            if self.failed_recognitions >= 5:
                self.log_conversation("System", "Multiple recognition failures, recalibrating microphone")
                self.calibrate_microphone()
                self.failed_recognitions = 0
            return None
        except sr.RequestError as e:
            self.log_conversation("System", f"Speech recognition error: {e}")
            return None
        except Exception as e:
            self.log_conversation("System", f"Recognition error: {e}")
            return None

    def navigate_section(self, section):
        if not self.driver:
            self.log_conversation("System", "No browser for navigation")
            return False
            
        try:
            result = self.driver.execute_script(f"""
                try {{
                    if (window.app && window.app.navigate) {{
                        window.app.navigate('{section}');
                        return 'success';
                    }}
                    return 'no_app';
                }} catch(e) {{
                    return 'error: ' + e.message;
                }}
            """)
            
            self.log_conversation("System", f"Navigation to {section}: {result}")
            
            if 'success' in str(result):
                time.sleep(2)
                return True
                
            return False
            
        except Exception as e:
            self.log_conversation("System", f"Navigation failed: {e}")
            return False

    def process_command(self, command):
        if not command:
            return

        self.log_conversation("User", f"Command: {command}")
        self.write_status('processing', command, '')

        command = command.lower()
        
        command_replacements = {
            "hassan": "asana",
            "hasan": "asana", 
            "assist": "assistant",
            "vr": "ar",
            "posture": "ar correction",
            "camera": "ar correction",
            "yoga poses": "asana",
            "pose library": "asana",
        }
        
        for wrong, correct in command_replacements.items():
            command = command.replace(wrong, correct)

        acknowledgement = self.get_acknowledgement()
        
        if any(word in command for word in ['home', 'dashboard', 'main']):
            success = self.navigate_section('dashboard')
            if success:
                self.speak(f"{acknowledgement} Taking you to the home screen where you can see your progress and daily insights.")
            else:
                self.speak("Navigating to home...")

        elif any(word in command for word in ['asana', 'pose', 'library', 'poses']):
            success = self.navigate_section('asana')
            if success:
                self.speak(f"{acknowledgement} Opening the yoga pose library. You can explore different poses and their benefits.")
            else:
                self.speak("Opening pose library...")

        elif any(word in command for word in ['ar', 'correction', 'camera', 'tracking', 'posture']):
            success = self.navigate_section('ar_correction')
            if success:
                self.speak(f"{acknowledgement} Starting AR posture correction. Stand about 6 feet from your camera for best results!")
            else:
                self.speak("Setting up camera correction...")

        elif any(word in command for word in ['routine', 'plan', 'workout', 'schedule']):
            success = self.navigate_section('routine')
            if success:
                self.speak(f"{acknowledgement} Opening your personalized routine. I'll show you today's recommended yoga sequence and meal suggestions based on your wellness data.")
            else:
                self.speak("Loading your routine...")

        elif any(word in command for word in ['assistant', 'chat', 'help', 'ai', 'virtual assistant']):
            success = self.navigate_section('assistant')
            if success:
                self.speak(f"{acknowledgement} I'm here to help! What would you like to know about yoga and wellness?")
            else:
                self.speak("Opening chat interface...")

        elif any(word in command for word in ['tadasana', 'mountain']):
            self.speak(f"{acknowledgement} Starting Tadasana pose correction.")
            self.navigate_section('ar_correction')

        elif any(word in command for word in ['downward', 'dog']):
            self.speak(f"{acknowledgement} Starting Downward Dog pose correction.")
            self.navigate_section('ar_correction')

        elif any(word in command for word in ['warrior']):
            self.speak(f"{acknowledgement} Starting Warrior III pose correction.")
            self.navigate_section('ar_correction')

        elif any(word in command for word in ['namastey', 'prayer']):
            self.speak(f"{acknowledgement} Starting Namastey pose correction.")
            self.navigate_section('ar_correction')

        elif any(word in command for word in ['test', 'working', 'status']):
            self.speak("I'm here and ready! Try saying 'Sunday open pose library' or 'Sunday start posture correction'.")

        elif any(word in command for word in ['thank', 'thanks']):
            self.speak("You're welcome! Happy to help with your yoga practice.")

        elif any(word in command for word in ['hello', 'hi', 'hey']):
            self.speak("Hello! I'm Sunday, your yoga assistant. How can I help you today?")

        elif any(word in command for word in ['read', 'tell', 'show']):
            if 'routine' in command:
                success = self.navigate_section('routine')
                if success:
                    self.speak(f"{acknowledgement} Opening your personalized routine. I'll show you today's recommended yoga sequence and meal suggestions based on your wellness data.")
            else:
                self.speak("I didn't catch that clearly. Feel free to try again when you're ready.")

        elif any(word in command for word in ['stop', 'quit', 'exit', 'shutdown', 'goodbye', 'deactivate']):
            self.speak("Thank you for your practice today! Namaste!")
            self.log_conversation("System", "Shutting down")
            time.sleep(2)
            self.log_conversation("System", "Shutdown complete")
            self.stop()

        else:
            self.speak("I didn't catch that clearly. Feel free to try again when you're ready.")

    def listen_loop(self):
        self.log_conversation("System", "Listening for wake word 'Sunday'...")
        
        wake_responses = [
            "Yes, I'm listening! What would you like to do?",
            "I'm here! How can I assist your practice?",
            "Yes, tell me how I can help!",
            "Hello! What shall we work on together?"
        ]
        
        similar_words = ['sundae', 'sundays', 'sunday\'s', 'someday']
        
        while self.listening:
            try:
                audio = self.listen_for_speech()
                if audio:
                    text = self.recognize_audio(audio)
                    if text:
                        if self.wake_word in text:
                            self.log_conversation("System", f"Wake word detected: {text}")
                            command = text.replace(self.wake_word, '').strip()
                            if command:
                                self.process_command(command)
                            else:
                                self.speak(random.choice(wake_responses))
                        elif any(word in text for word in similar_words):
                            self.speak("Did you call me? I heard something similar to Sunday. If you need me, just say 'Sunday' clearly.")
                            
            except Exception as e:
                self.log_conversation("System", f"Listen loop error: {e}")
                time.sleep(1)

    def stop(self):
        self.listening = False
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        self.log_conversation("System", "Sunday AI stopped")
        sys.exit(0)

    def run(self):
        try:
            while self.listening:
                time.sleep(1)
        except KeyboardInterrupt:
            self.log_conversation("System", "KeyboardInterrupt received")
            self.stop()

if __name__ == "__main__":
    try:
        assistant = AIVoiceAssistant()
        assistant.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        if 'assistant' in locals():
            assistant.stop()
    except Exception as e:
        print(f"Fatal error: {e}")
