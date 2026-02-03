import subprocess
import time
import sys
import os

def start_platform():
    """
    Unified start script for SUNDAY Wellness Platform.
    Starts the Flask app (Backend/Web) and the AI Voice Assistant (Voice/AR).
    """
    print("\n" + "="*50)
    print("   🧘 SUNDAY WELLNESS PLATFORM - UNIFIED START 🧘")
    print("="*50 + "\n")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Start Flask App
    print("🚀 [1/2] Starting Web Server (Flask + MongoDB)...")
    app_proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=base_dir,
        # We don't pipe stdout to keep it visible for debugging, 
        # but you can use subprocess.DEVNULL if you want it quiet.
        stdout=None, 
        stderr=None
    )
    
    print("⏳ Waiting for server to initialize (5s)...")
    time.sleep(5)
    
    # 2. Start Voice Assistant
    print("🚀 [2/2] Starting AI Voice Assistant...")
    print("👉 A Chrome window will open. Please log in or register to begin.")
    print("👉 Once you are at the Home screen, say 'Sunday' to activate me.")
    print("👉 Press Ctrl+C in this terminal to shut down everything.")
    
    try:
        assistant_proc = subprocess.Popen(
            [sys.executable, "assistant.py"],
            cwd=base_dir
        )
        
        # Wait for the assistant to finish
        assistant_proc.wait()
        
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down SUNDAY Wellness Platform...")
    except Exception as e:
        print(f"\n❌ Error during execution: {e}")
    finally:
        # Cleanup processes
        print("🧹 Cleaning up processes...")
        app_proc.terminate()
        try:
            assistant_proc.terminate()
        except:
            pass
        
        print("\n✨ Done. Namaste!\n")

if __name__ == "__main__":
    start_platform()
