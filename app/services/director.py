import json
import time
import threading
import os
import requests

class SceneDirector:
    def __init__(self, config_path="tour_config.json", obs_manager=None, workers_map=None, scene_lookup_cb=None):
        self.config_path = config_path
        self.obs = obs_manager
        self.workers = workers_map or {}
        self.scene_lookup = scene_lookup_cb
        self.cues = []
        self.is_running = False
        self.current_cue_idx = 0
        self.skip_flag = False
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
            self.skip_flag = False
            threading.Thread(target=self._tour_loop, daemon=True).start()
            print("\n[DIRECTOR] ▶ AUTOMATED TOUR STARTED")
        return True

    def stop_tour(self):
        if self.is_running:
            self.is_running = False
            self.skip_flag = True # Break any sleep immediately
            print("\n[DIRECTOR] ⏹ AUTOMATED TOUR STOPPED")

    def trigger_cue(self, idx):
        """Fires immediately when the UI 'GO' button is pressed."""
        if 0 <= idx < len(self.cues):
            self.current_cue_idx = idx
            if self.is_running:
                # If running, flag the sleep to break; loop will instantly pick up the new index
                self.skip_flag = True
            else:
                # If stopped, just execute the cue standalone
                cue = self.cues[idx]
                cam = cue.get('camera_id', 'cam_1')
                action = cue.get('action', 'preset_1')
                scene = self.scene_lookup(cam) if self.scene_lookup else "Unknown"
                
                self._send_camera_action(cam, action, cue.get('is_moving_shot', False), label=f"Manual GO: {scene}")
                if self.obs and self.obs.connected:
                    self.obs.set_scene(scene)
                self._send_camera_action(cam, "status_only", False, label=f"Manual GO: {scene} (LIVE ON AIR)")

    def _send_camera_action(self, camera_id, action, is_moving_shot, label=""):
        worker_url = self.workers.get(camera_id)
        if not worker_url: return

        payload = {
            "action": action, 
            "allow_movement_on_program": is_moving_shot,
            "label": label
        }
        try: requests.post(f"{worker_url}/api/action", json=payload, timeout=1.0)
        except: pass

    def _tour_loop(self):
        while self.is_running:
            if not self.cues:
                self.is_running = False
                break
                
            cue = self.cues[self.current_cue_idx]
            
            if not cue.get("enabled", True):
                self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)
                time.sleep(0.5)
                continue
                
            cam = cue.get('camera_id', 'cam_1')
            action = cue.get('action', 'preset_1')
            scene = self.scene_lookup(cam) if self.scene_lookup else "Unknown"
            
            print(f"\n[DIRECTOR] --- PREPARING CUE: {scene} ---")
            
            self._send_camera_action(cam, action, cue.get('is_moving_shot', False), label=f"Cue: {scene} (Settling)")
            
            settle = float(cue.get("settle_time_sec", 4.0))
            self._interruptible_sleep(settle)
            
            if not self.is_running: break
            if self.skip_flag: 
                self.skip_flag = False
                continue # Jump immediately to the newly requested index
            
            print(f"[DIRECTOR] 🔴 TAKING LIVE: {scene}")
            if self.obs and self.obs.connected:
                self.obs.set_scene(scene)
            
            self._send_camera_action(cam, "status_only", False, label=f"Cue: {scene} (LIVE ON AIR)")
                
            live_time = float(cue.get("live_duration_sec", 10.0))
            self._interruptible_sleep(live_time)
            
            if not self.is_running: break
            if self.skip_flag: 
                self.skip_flag = False
                continue 
            
            self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)

    def _interruptible_sleep(self, duration_sec):
        """Allows instant abortion of the sleep timer via skip_flag."""
        elapsed = 0
        while elapsed < duration_sec and self.is_running and not self.skip_flag:
            time.sleep(0.1)
            elapsed += 0.1