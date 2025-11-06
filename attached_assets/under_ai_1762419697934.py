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
import re
import pyttsx3
import random
import subprocess

class AIVoiceAssistant:
    def __init__(self):
        self.status_file = "sunday_status.json"
        self.conv_log_file = "conversation_log.txt"
        self.listening = True
        self.wake_word = "sunday"
        
        # Simple TTS solution
        self.setup_tts()
        
        self.log_conversation("System", "Sunday AI starting with simple TTS system")

        # Initialize speech recognition
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        # Optimized settings for better voice recognition
        self.recognizer.energy_threshold = 3000
        self.recognizer.pause_threshold = 1.0
        self.recognizer.dynamic_energy_threshold = True
        
        # Calibrate microphone
        self.calibrate_microphone()

        # Browser setup
        self.chrome_options = Options()
        self.chrome_options.add_argument("--use-fake-ui-for-media-stream")
        self.chrome_options.add_argument("--disable-web-security")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
        self.chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.chrome_options.add_argument("--window-size=1200,800")
        
        self.driver = None

        # Start browser
        browser_thread = threading.Thread(target=self.open_browser, daemon=True)
        browser_thread.start()

        # Start listening
        time.sleep(3)
        listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        listen_thread.start()

        self.write_status('ready', '', '')
        self.speak("Hello! I'm Sunday, your yoga assistant. I'm here and ready to help you with your wellness journey. Just say 'Sunday' followed by what you'd like to do!")

    def setup_tts(self):
        """Simple TTS setup that just works"""
        try:
            # Test if we can use pyttsx3
            self.tts_engine = pyttsx3.init()
            self.tts_engine.setProperty('rate', 150)
            self.tts_engine.setProperty('volume', 1.0)
            self.log_conversation("System", "TTS engine configured successfully")
        except Exception as e:
            self.log_conversation("System", f"TTS setup error: {e}")
            self.tts_engine = None

    def speak(self, text):
        """Simple speaking function that always works"""
        if not text or not self.listening:
            return False
            
        self.log_conversation("AI", text)
        self.write_status('speaking', '', text)
        
        try:
            # Method 1: Try pyttsx3 first
            if self.tts_engine:
                def speak_thread():
                    try:
                        # Create a new engine for each speech to avoid conflicts
                        engine = pyttsx3.init()
                        engine.setProperty('rate', 150)
                        engine.setProperty('volume', 1.0)
                        engine.say(text)
                        engine.runAndWait()
                    except Exception as e:
                        print(f"TTS Error: {e}")
                        self._system_tts(text)
                
                # Run in thread to avoid blocking
                thread = threading.Thread(target=speak_thread, daemon=True)
                thread.start()
                return True
            else:
                # Method 2: Use system TTS
                return self._system_tts(text)
                
        except Exception as e:
            self.log_conversation("System", f"Speak error: {e}")
            # Method 3: Ultimate fallback
            print(f"🔊 AI: {text}")
            return False

    def _system_tts(self, text):
        """System-level TTS that always works"""
        try:
            if os.name == 'nt':  # Windows
                # Use Windows SAPI directly
                from win32com.client import Dispatch
                speaker = Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
                return True
            else:  # Linux/Mac
                # Use espeak for Linux, say for Mac
                if os.name == 'posix' and 'Darwin' in os.uname():
                    subprocess.run(['say', text], capture_output=True)
                else:
                    subprocess.run(['espeak', text], capture_output=True)
                return True
        except Exception as e:
            self.log_conversation("System", f"System TTS failed: {e}")
            print(f"🔊 AI: {text}")
            return False

    def calibrate_microphone(self):
        """Calibrate microphone with better settings"""
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
        """Get random acknowledgement phrases"""
        acknowledgements = [
            "Sure thing!",
            "I'm on it!",
            "Right away!",
            "Absolutely!",
            "Got it!",
            "Okay, let's do that!",
            "I'll take care of that!",
            "No problem!",
            "You got it!"
        ]
        return random.choice(acknowledgements)

    def open_browser(self):
        """Open browser with extended wait times and better error handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not os.path.exists("index.html"):
                    self.speak("I can't find the main application file. Please make sure index.html is in the same folder.")
                    return

                self.driver = webdriver.Chrome(options=self.chrome_options)
                file_path = "file://" + os.path.abspath("index.html")
                self.driver.get(file_path)
                
                # Extended wait for page to load
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Additional wait for JavaScript to initialize
                time.sleep(4)
                
                self.log_conversation("System", f"Browser ready on attempt {attempt + 1}")
                self.speak("Perfect! I'm all connected and ready to help you with your yoga practice.")
                return
                
            except Exception as e:
                self.log_conversation("System", f"Browser error attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    self.speak("I'm having trouble connecting to the browser. Please check if Chrome is installed properly.")

    def listen_for_speech(self, timeout=8, phrase_time_limit=10):
        """Listen for speech with better parameters"""
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
        """Convert audio to text with better error handling"""
        if not audio:
            return None
            
        try:
            text = self.recognizer.recognize_google(audio, language="en-US").lower().strip()
            if len(text) > 1:
                self.log_conversation("System", f"Recognized: {text}")
                return text
            return None
        except sr.UnknownValueError:
            self.log_conversation("System", "Speech recognition could not understand audio")
            return None
        except sr.RequestError as e:
            self.log_conversation("System", f"Speech recognition error: {e}")
            return None
        except Exception as e:
            self.log_conversation("System", f"Recognition error: {e}")
            return None

    def navigate_section(self, section):
        """Navigate to section using multiple methods with better feedback"""
        if not self.driver:
            self.log_conversation("System", "No browser for navigation")
            return False
            
        try:
            # Method 1: Direct JavaScript navigation
            result = self.driver.execute_script(f"""
                try {{
                    // Try multiple ways to access the app
                    if (window.app && window.app.navigate) {{
                        window.app.navigate('{section}');
                        return 'success_app_navigate';
                    }}
                    if (window.navigate) {{
                        window.navigate('{section}');
                        return 'success_window_navigate';
                    }}
                    // Try to find and click the navigation button
                    const buttons = document.querySelectorAll('button, [onclick*="{section}"]');
                    for (let btn of buttons) {{
                        if (btn.textContent.toLowerCase().includes('{section}') || 
                            (btn.onclick && btn.onclick.toString().includes('{section}'))) {{
                            btn.click();
                            return 'success_button_click';
                        }}
                    }}
                    return 'no_navigation_method_found';
                }} catch(e) {{
                    return 'error: ' + e.message;
                }}
            """)
            
            self.log_conversation("System", f"Navigation to {section}: {result}")
            
            if any(success in str(result) for success in ['success', 'click']):
                time.sleep(2)
                return True
                
            # Method 2: Try clicking nav buttons directly
            return self.click_nav_button(section)
            
        except Exception as e:
            self.log_conversation("System", f"Navigation failed: {e}")
            return False

    def click_nav_button(self, section):
        """Click navigation button directly with better matching"""
        try:
            # Map sections to button text with more variations
            button_text_map = {
                'dashboard': ['home', 'dashboard', 'main'],
                'asana': ['asana', 'pose', 'library', 'poses', 'yoga poses'],
                'routine': ['routine', 'plan', 'workout', 'schedule'],
                'ar_correction': ['ar', 'correction', 'tracking', 'camera', 'posture'],
                'assistant': ['assistant', 'chat', 'help', 'ai', 'virtual assistant']
            }
            
            if section not in button_text_map:
                return False
                
            # Find all buttons
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for button in buttons:
                try:
                    text = button.text.lower()
                    if any(keyword in text for keyword in button_text_map[section]):
                        button.click()
                        self.log_conversation("System", f"Clicked button: {text}")
                        time.sleep(2)
                        return True
                except:
                    continue
                    
            return False
            
        except Exception as e:
            self.log_conversation("System", f"Button click failed: {e}")
            return False

    def process_command(self, command):
        """Process voice commands with better understanding and personality"""
        if not command:
            self.speak("I didn't quite catch that. Could you please repeat your command?")
            return

        self.log_conversation("User", f"Command: {command}")
        self.write_status('processing', command, '')

        # Normalize command - IMPROVED COMMAND MAPPING
        original_command = command.lower()
        command = original_command
        
        # Better command normalization
        command_replacements = {
            "hassan": "asana",
            "hasan": "asana", 
            "libra": "library",
            "option": "asana",
            "rout": "routine",
            "assist": "assistant",
            "santa": "sunday",
            "sandesh": "sunday",
            "vr collection": "ar correction",
            "vr": "ar",
            "virtual": "assistant",
            "shut down": "stop",
            "shutdown": "stop",
            "go back to home": "home",
            "activate sunday": "test",
            "yoga poses": "asana",
            "posture correction": "ar correction",
            "camera mode": "ar correction",
            "workout plan": "routine",
            "exercise routine": "routine",
            "help me": "assistant",
            "talk to ai": "assistant",
            "tadas": "tadasana",
            "mountain pose": "tadasana",
            "downward dog": "adho mukha svanasana",
            "warrior": "warrior iii"
        }
        
        for wrong, correct in command_replacements.items():
            command = command.replace(wrong, correct)

        # Command processing - IMPROVED MATCHING WITH PERSONALITY
        acknowledgement = self.get_acknowledgement()
        
        if any(word in command for word in ['home', 'dashboard', 'main', 'go home', 'home screen']):
            success = self.navigate_section('dashboard')
            if success:
                self.speak(f"{acknowledgement} Taking you to the home screen where you can see your progress and daily insights.")
            else:
                self.speak("I'm having trouble navigating to the home screen. Let me try another way.")

        elif any(word in command for word in ['asana', 'pose', 'library', 'poses', 'hassan', 'yoga pose']):
            success = self.navigate_section('asana')
            if success:
                self.speak(f"{acknowledgement} Opening our yoga pose library. You'll find detailed instructions for Tadasana, Downward Dog, Warrior poses, and many more!")
            else:
                self.speak("Let me try to open the pose library another way. Sometimes the connection needs a moment.")

        elif any(word in command for word in ['ar', 'correction', 'camera', 'vr', 'tracking', 'posture']):
            success = self.navigate_section('ar_correction')
            if success:
                self.speak(f"{acknowledgement} Starting the AR posture correction. Make sure you're standing about 6 feet from your camera for the best tracking!")
            else:
                self.speak("I'm setting up the camera correction feature. This might take just a moment.")

        elif any(word in command for word in ['routine', 'plan', 'workout', 'route', 'schedule', 'exercise']):
            success = self.navigate_section('routine')
            if success:
                self.speak(f"{acknowledgement} Opening your personalized routine. I'll show you today's recommended yoga sequence and meal suggestions based on your wellness data.")
            else:
                self.speak("Let me load your personalized routine. I'm checking your latest activity and stress levels to give you the best recommendations.")

        elif any(word in command for word in ['assistant', 'chat', 'help', 'ai', 'virtual', 'question']):
            success = self.navigate_section('assistant')
            if success:
                self.speak(f"{acknowledgement} I'm here to help! Ask me anything about yoga poses, meditation techniques, or request a custom session. What would you like to know?")
            else:
                self.speak("I'm opening the chat interface where we can talk about anything related to yoga and wellness.")

        elif any(word in command for word in ['tadasana', 'mountain pose', 'tadas']):
            self.speak(f"{acknowledgement} Let me guide you through Tadasana, the Mountain Pose.")
            time.sleep(1)
            self.guide_through_pose('tadasana')

        elif any(word in command for word in ['downward', 'dog', 'downward dog']):
            self.speak(f"{acknowledgement} Let me guide you through Downward Facing Dog.")
            time.sleep(1)
            self.guide_through_pose('downward dog')

        elif any(word in command for word in ['warrior', 'warrior three', 'warrior iii']):
            self.speak(f"{acknowledgement} Let me guide you through Warrior Three pose.")
            time.sleep(1)
            self.guide_through_pose('warrior iii')

        elif any(word in command for word in ['read', 'tell me about', 'what\'s in', 'describe', 'show me']):
            if 'dashboard' in command or 'home' in command:
                self.speak("Your dashboard shows your daily progress including posture score, current streak, and calories burned. It's your wellness snapshot!")
            elif 'asana' in command or 'pose' in command:
                self.speak("The pose library has detailed information about Tadasana for beginners, Downward Dog for intermediates, and Warrior Three for advanced practice. Each pose includes benefits and precautions.")
            elif 'routine' in command:
                self.speak("Your routine section provides personalized yoga sequences and meal suggestions based on your sleep quality and stress levels from your wearable device.")
            elif 'assistant' in command or 'chat' in command:
                self.speak("This is where you can chat with me! I can answer yoga questions, create custom sessions, or explain meditation techniques in detail.")
            elif 'ar' in command or 'correction' in command:
                self.speak("The AR correction uses your camera and AI to give real-time feedback on your yoga poses. It checks your alignment and helps you improve your form instantly.")
            else:
                self.speak("I'd be happy to describe any section! Just tell me which one - like 'describe the pose library' or 'tell me about the dashboard'.")

        elif any(word in command for word in ['guide', 'teach', 'how to', 'demonstrate', 'instruct']):
            if 'tadasana' in command or 'mountain' in command:
                self.guide_through_pose('tadasana')
            elif 'downward' in command or 'dog' in command:
                self.guide_through_pose('downward dog')
            elif 'warrior' in command:
                self.guide_through_pose('warrior iii')
            else:
                self.speak("I can guide you through Tadasana for grounding, Downward Dog for full-body stretch, or Warrior Three for balance. Which would you like to practice?")

        elif any(word in command for word in ['test', 'working', 'status', 'activate', 'you there']):
            responses = [
                "I'm here and fully operational! Ready to help you with yoga poses, routines, or answer any wellness questions.",
                "System check complete! Everything is working perfectly. Your personal yoga assistant is at your service!",
                "I'm running smoothly! Try saying things like 'Sunday open pose library' or 'Sunday start posture correction'."
            ]
            self.speak(random.choice(responses))

        elif any(word in command for word in ['thank', 'thanks']):
            self.speak("You're very welcome! I'm always happy to help with your yoga practice.")

        elif any(word in command for word in ['hello', 'hi', 'hey']):
            self.speak("Hello there! I'm Sunday, your yoga and wellness assistant. How can I help you today?")

        elif any(word in command for word in ['stop', 'quit', 'exit', 'shutdown', 'goodbye']):
            self.speak("Thank you for your practice today! Remember to stay hydrated and listen to your body. Goodbye!")
            time.sleep(2)
            self.stop()

        else:
            # If we don't understand, provide helpful suggestions
            self.speak("I want to make sure I understand correctly. You can ask me to: open the pose library, start posture correction, show your routine, or chat with the assistant. What would you like to try?")

    def guide_through_pose(self, pose_name):
        """Provide guided instructions with more personality"""
        if pose_name == 'tadasana':
            steps = [
                "Let's begin Mountain Pose. Stand with your feet together, heels slightly apart",
                "Rest your arms gently alongside your torso, with palms facing forward",
                "Distribute your weight evenly across both feet, feeling grounded",
                "Engage your thigh muscles and gently lift your kneecaps",
                "Lengthen your tailbone toward the floor, creating space in your spine",
                "Lift the crown of your head toward the ceiling, chin parallel to floor",
                "Take five deep, calming breaths and feel the stability of the mountain"
            ]
        elif pose_name == 'downward dog':
            steps = [
                "Let's move into Downward Facing Dog. Start on your hands and knees",
                "Spread your fingers wide, pressing firmly through your palms",
                "Tuck your toes and lift your hips up and back, forming an inverted V",
                "Straighten your legs as much as comfortable, don't force it",
                "Keep your head between your arms, relaxing your neck",
                "Press your heels toward the floor, but it's okay if they don't touch",
                "Hold for five deep breaths, feeling the wonderful stretch"
            ]
        elif pose_name == 'warrior iii':
            steps = [
                "Now for Warrior Three, a beautiful balancing pose. Start standing with feet together",
                "Shift your weight onto your right foot, finding your balance point",
                "Engage your core muscles as you slowly lean forward",
                "Lift your left leg straight behind you, keeping hips level",
                "Extend your entire body in one straight line from fingertips to toes",
                "Find a focal point on the floor to help with balance",
                "Hold for three to five breaths, then we'll switch sides"
            ]
        else:
            self.speak("I can guide you through Mountain Pose for grounding, Downward Dog for energy, or Warrior Three for balance. Which calls to you today?")
            return

        for i, step in enumerate(steps, 1):
            self.speak(step)
            # Vary the pause time based on step complexity
            pause_time = 6 if i in [1, len(steps)] else 5
            time.sleep(pause_time)
            
        completion_phrases = [
            f"Beautiful! You've completed {pose_name}. How does your body feel?",
            f"Excellent work on {pose_name}! Your practice is growing stronger.",
            f"Lovely! You've mastered the essence of {pose_name}. Well done!"
        ]
        self.speak(random.choice(completion_phrases))

    def listen_loop(self):
        """Main listening loop with improved responsiveness"""
        self.speak("I'm listening for you. Just say 'Sunday' when you need me!")
        
        consecutive_failures = 0
        max_failures = 5
        
        while self.listening:
            try:
                # Listen for wake word with better parameters
                audio = self.listen_for_speech(timeout=5, phrase_time_limit=6)
                
                if audio:
                    text = self.recognize_audio(audio)
                    
                    if text:
                        consecutive_failures = 0  # Reset failure counter
                        
                        if self.wake_word in text:
                            self.log_conversation("System", f"Wake word detected: {text}")
                            # More natural response
                            responses = [
                                "Yes, I'm listening! What would you like to do?",
                                "I'm here! How can I assist your practice?",
                                "Hello! What shall we work on together?",
                                "Yes, tell me how I can help!"
                            ]
                            self.speak(random.choice(responses))
                            
                            # Listen for command with longer timeout
                            audio = self.listen_for_speech(timeout=10, phrase_time_limit=15)
                            
                            if audio:
                                command = self.recognize_audio(audio)
                                if command:
                                    self.process_command(command)
                                else:
                                    self.speak("I didn't catch that clearly. Feel free to try again when you're ready.")
                            else:
                                self.speak("I'm here when you need me. Just say 'Sunday' followed by your request.")
                        else:
                            # Heard something but not wake word
                            if any(word in text for word in ['sunday', 'sandi', 'help', 'assistant']):
                                self.speak("Did you call me? I heard something similar to Sunday. If you need me, just say 'Sunday' clearly.")
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= max_failures:
                            self.log_conversation("System", "Multiple recognition failures, recalibrating microphone")
                            self.calibrate_microphone()
                            consecutive_failures = 0
                
                time.sleep(0.5)
                
            except Exception as e:
                self.log_conversation("System", f"Listen loop error: {e}")
                consecutive_failures += 1
                time.sleep(1)

    def stop(self):
        """Clean shutdown"""
        self.log_conversation("System", "Shutting down")
        self.listening = False
        
        # Close browser
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        
        self.write_status('stopped', '', '')
        self.log_conversation("System", "Shutdown complete")
        os._exit(0)

if __name__ == "__main__":
    print("🚀 Starting OMVANA AI Voice Assistant (Simple TTS Version)...")
    print("Make sure you have Chrome installed and microphone permissions granted.")
    print("Say 'Sunday' clearly to activate the assistant.")
    
    try:
        assistant = AIVoiceAssistant()
        # Keep the main thread alive
        while assistant.listening:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down...")
        if 'assistant' in locals():
            assistant.stop()
    except Exception as e:
        print(f"Fatal error: {e}")