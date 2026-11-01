import subprocess
import sys
import time

print("==============================================")
print("        PTZ DIRECTOR - BOOT SEQUENCE          ")
print("==============================================")

try:
    print("[BOOT] Launching Camera 1 Worker (Port 8001)...")
    w1 = subprocess.Popen([sys.executable, "app/worker.py"])
    
    print("[BOOT] Launching Camera 2 Worker (Port 8002)...")
    w2 = subprocess.Popen([sys.executable, "app/worker2.py"])
    
    time.sleep(2)
    print("[BOOT] Launching UI Hub (Port 8000)...")
    hub = subprocess.Popen([sys.executable, "app/main.py"])
    
    print("\n[SYSTEM] All services are online.")
    print("[SYSTEM] Access the dashboard at http://localhost:8000")
    print("[SYSTEM] Press CTRL+C to gracefully shut down.")
    
    hub.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    w1.terminate()
    w2.terminate()
    hub.terminate()