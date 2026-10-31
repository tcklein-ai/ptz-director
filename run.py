import subprocess
import sys
import time

def main():
    print("==============================================")
    print("        PTZ DIRECTOR - BOOT SEQUENCE          ")
    print("==============================================\n")
    
    # Start the Camera Worker (Port 8001)
    print("[BOOT] Launching Camera Worker...")
    worker_process = subprocess.Popen([sys.executable, "-m", "app.worker"])
    
    # Give the worker 2 seconds to initialize and bind its port 
    # so it's ready to receive the config JSON from the Hub
    time.sleep(2)
    
    # Start the UI Hub (Port 8000)
    print("[BOOT] Launching UI Hub...")
    hub_process = subprocess.Popen([sys.executable, "-m", "app.main"])
    
    print("\n[SYSTEM] All services are online.")
    print("[SYSTEM] Access the dashboard at http://localhost:8000")
    print("[SYSTEM] Press CTRL+C to gracefully shut down both servers.\n")
    print("----------------------------------------------")
    
    try:
        # Keep this master script alive and watching the sub-processes
        worker_process.wait()
        hub_process.wait()
    except KeyboardInterrupt:
        print("\n[SYSTEM] CTRL+C detected. Initiating shutdown sequence...")
        
        # Terminate both child processes cleanly
        hub_process.terminate()
        worker_process.terminate()
        
        # Wait for them to finish closing out
        hub_process.wait()
        worker_process.wait()
        
        print("[SYSTEM] All services successfully shut down. Goodbye!")

if __name__ == "__main__":
    main()