import subprocess
import sys
import time

print("==============================================")
print("        PTZ DIRECTOR - BOOT SEQUENCE          ")
print("==============================================")

try:
    print("[BOOT] Launching Camera 1 Worker (Port 8001)...")
    # Added the "-m" flag to execute them as modules from the root directory
    w1 = subprocess.Popen([sys.executable, "-m", "app.worker"])
    
    print("[BOOT] Launching Camera 2 Worker (Port 8002)...")
    w2 = subprocess.Popen([sys.executable, "-m", "app.worker2"])
    
    time.sleep(2)
    print("[BOOT] Launching UI Hub (Port 8000)...")
    hub = subprocess.Popen([sys.executable, "-m", "app.main"])
    
    print("\n[SYSTEM] All services are online.")
    print("[SYSTEM] Access the dashboard at http://localhost:8000")
    print("[SYSTEM] Press CTRL+C to gracefully shut down.")
    
    hub.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    w1.terminate()
    w2.terminate()
    hub.terminate()