import json
import time
import threading
import os
import requests

class SceneDirector:
    """Manages the Automated Scene Tour using Leapfrog (A/B) timing."""
    
    def __init__(self, config_path="tour_config.json", obs_manager=None, workers_map=None):
        self.config_path = config_path
        self.obs = obs_manager
        
        # A dictionary mapping camera IDs to their worker URLs 
        # e.g., {"cam_1": "http://127.0.0.1:8001"}
        self.workers = workers_map or {} 
        
        self.cues = []
        self.is_running = False
        self.current_cue_idx = 0
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    self.cues = json.load(f)
                print(f"[DIRECTOR] Loaded {len(self.cues)} sequence cues.")
            except Exception as e:
                print(f"[DIRECTOR] Error loading tour_config: {e}")
        else:
            print("[DIRECTOR] No tour_config.json found.")

    def start_tour(self):
        self.load_config() # Always pull fresh config in case UI changed it
        if not self.cues:
            print("[DIRECTOR] Cannot start tour. No cues loaded.")
            return False
        
        if not self.is_running:
            self.is_running = True
            self.current_cue_idx = 0
            threading.Thread(target=self._tour_loop, daemon=True).start()
            print("\n[DIRECTOR] ▶ AUTOMATED TOUR STARTED")
        return True

    def stop_tour(self):
        if self.is_running:
            self.is_running = False
            print("\n[DIRECTOR] ⏹ AUTOMATED TOUR STOPPED")

    def _send_camera_action(self, camera_id, action, is_moving_shot):
        worker_url = self.workers.get(camera_id)
        if not worker_url:
            print(f"[DIRECTOR] Warning: No worker URL mapped for {camera_id}")
            return

        print(f"[DIRECTOR] Command {camera_id} -> {action} (Moving Live: {is_moving_shot})")
        
        # We hit an explicit action endpoint on the worker 
        # (We will add this endpoint to the worker momentarily)
        payload = {
            "action": action, 
            "allow_movement_on_program": is_moving_shot
        }
        
        try:
            requests.post(f"{worker_url}/api/action", json=payload, timeout=1.0)
        except requests.exceptions.RequestException:
            print(f"[DIRECTOR] Failed to reach worker {camera_id}")

    def _tour_loop(self):
        """The core state machine for Leapfrog sequence timing."""
        while self.is_running:
            cue = self.cues[self.current_cue_idx]
            
            print(f"\n======================================")
            print(f"[DIRECTOR] --- PREPARING CUE {cue.get('cue_number', self.current_cue_idx + 1)} ---")
            
            # --- PHASE 1: OFFLINE SETUP ---
            self._send_camera_action(
                camera_id=cue.get('camera_id'),
                action=cue.get('action'),
                is_moving_shot=cue.get('is_moving_shot', False)
            )
            
            # --- PHASE 2: SETTLE TIME ---
            # Wait for the offline camera to physically move and focus
            settle = cue.get("settle_time_sec", 4.0)
            print(f"[DIRECTOR] Settling offline camera for {settle}s...")
            self._interruptible_sleep(settle)
            if not self.is_running: break
            
            # --- PHASE 3: THE CUT ---
            obs_scene = cue.get('obs_scene')
            print(f"[DIRECTOR] 🔴 TAKING LIVE: {obs_scene}")
            if self.obs and self.obs.connected:
                self.obs.set_scene(obs_scene)
                
            # --- PHASE 4: ON-AIR DURATION ---
            live_time = cue.get("live_duration_sec", 10.0)
            print(f"[DIRECTOR] Holding Live for {live_time}s...")
            self._interruptible_sleep(live_time)
            if not self.is_running: break
            
            # --- PHASE 5: ADVANCE ---
            # Loop back to the first cue if we hit the end
            self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)

    def _interruptible_sleep(self, duration_sec):
        """Allows immediate abortion of the tour during a long wait block."""
        elapsed = 0
        while elapsed < duration_sec and self.is_running:
            time.sleep(0.1)
            elapsed += 0.1