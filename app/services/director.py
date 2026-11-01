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

    def start_tour(self):
        self.load_config() 
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

    def _send_camera_action(self, camera_id, action, is_moving_shot, label=""):
        worker_url = self.workers.get(camera_id)
        if not worker_url: return

        # Passing a 'label' allows the worker to print status to the UI terminal
        payload = {
            "action": action, 
            "allow_movement_on_program": is_moving_shot,
            "label": label
        }
        try:
            requests.post(f"{worker_url}/api/action", json=payload, timeout=1.0)
        except requests.exceptions.RequestException:
            pass

    def _tour_loop(self):
        """The core state machine for Leapfrog sequence timing."""
        while self.is_running:
            if not self.cues:
                self.is_running = False
                break
                
            cue = self.cues[self.current_cue_idx]
            
            # Skip disabled cues gracefully
            if not cue.get("enabled", True):
                self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)
                time.sleep(0.5)
                continue
                
            scene = cue.get('obs_scene', 'Unknown')
            cam = cue.get('camera_id', 'Unknown')
            action = cue.get('action', 'Unknown')
            
            print(f"\n[DIRECTOR] --- PREPARING CUE: {scene} ---")
            
            # 1. Command Offline Camera & Update Terminal
            self._send_camera_action(cam, action, cue.get('is_moving_shot', False), label=f"Cue: {scene} (Settling)")
            
            # 2. Settle Time
            settle = float(cue.get("settle_time_sec", 4.0))
            print(f"[DIRECTOR] Settling {cam} for {settle}s...")
            self._interruptible_sleep(settle)
            if not self.is_running: break
            
            # 3. The Cut
            print(f"[DIRECTOR] 🔴 TAKING LIVE: {scene}")
            if self.obs and self.obs.connected:
                self.obs.set_scene(scene)
            
            # Update Worker Terminal to show it's Live
            self._send_camera_action(cam, "status_only", False, label=f"Cue: {scene} (LIVE ON AIR)")
                
            # 4. Live Duration
            live_time = float(cue.get("live_duration_sec", 10.0))
            print(f"[DIRECTOR] Holding Live for {live_time}s...")
            self._interruptible_sleep(live_time)
            if not self.is_running: break
            
            # 5. Advance Sequence
            self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)

    def _interruptible_sleep(self, duration_sec):
        """Allows immediate abortion of the tour during a long wait block."""
        elapsed = 0
        while elapsed < duration_sec and self.is_running:
            time.sleep(0.1)
            elapsed += 0.1