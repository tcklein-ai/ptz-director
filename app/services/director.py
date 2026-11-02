import json
import time
import threading
import os
import requests

class SceneDirector:
    def __init__(self, config_path="tour_config.json", obs_manager=None, workers_map=None, scene_lookup_cb=None, current_scene_cb=None):
        self.config_path = config_path
        self.obs = obs_manager
        self.workers = workers_map or {}
        self.scene_lookup = scene_lookup_cb
        self.current_scene_cb = current_scene_cb
        
        self.cues = []
        self.is_running = False
        self.current_cue_idx = 0
        self.skip_flag = False
        
        self.phase = "IDLE"
        self.timer_duration = 0.0
        self.timer_elapsed = 0.0
        self.tour_error = ""
        
        self.load_config()

    def get_status(self):
        return {
            "phase": self.phase,
            "timer_duration": self.timer_duration,
            "timer_elapsed": self.timer_elapsed,
            "error": self.tour_error
        }

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    self.cues = json.load(f)
            except Exception: pass

    def start_tour(self):
        self.load_config() 
        if not self.cues: return False
        
        if not self.is_running:
            self.is_running = True
            self.current_cue_idx = 0
            self.skip_flag = False
            self.tour_error = ""
            threading.Thread(target=self._tour_loop, daemon=True).start()
        return True

    def stop_tour(self):
        if self.is_running:
            self.is_running = False
            self.skip_flag = True 
            self.phase = "IDLE"

    def trigger_cue(self, idx):
        if 0 <= idx < len(self.cues):
            self.current_cue_idx = idx
            self.tour_error = ""
            if self.is_running:
                self.skip_flag = True
            else:
                cue = self.cues[idx]
                cam = cue.get('camera_id', 'cam_1')
                action = cue.get('action', 'preset_1')
                scene = self.scene_lookup(cam) if self.scene_lookup else "Unknown"
                self._send_camera_action(cam, action, cue.get('is_moving_shot', False), label=f"Manual GO: {scene}")
                if self.obs and self.obs.connected and scene != "Unknown": 
                    self.obs.set_scene(scene)
                self._send_camera_action(cam, "status_only", False, label=f"Manual GO: {scene} (LIVE ON AIR)")

    def _send_camera_action(self, camera_id, action, is_moving_shot, label=""):
        worker_url = self.workers.get(camera_id)
        if not worker_url: return
        payload = {"action": action, "allow_movement_on_program": is_moving_shot, "label": label}
        try: requests.post(f"{worker_url}/api/action", json=payload, timeout=1.0)
        except: pass

    def _prep_off_air_cameras(self, live_cue_idx):
        if not self.cues: return
        live_cue = self.cues[live_cue_idx]
        live_cam = live_cue.get('camera_id', 'cam_1')
        prepped_cams = set([live_cam]) 
        
        for offset in range(1, len(self.cues)):
            search_idx = (live_cue_idx + offset) % len(self.cues)
            next_cue = self.cues[search_idx]
            
            if not next_cue.get("enabled", True): 
                continue
                
            next_cam = next_cue.get('camera_id', 'cam_1')
            if next_cam not in prepped_cams:
                action = next_cue.get('action', 'preset_1')
                scene = self.scene_lookup(next_cam) if self.scene_lookup else "Unknown"
                self._send_camera_action(next_cam, action, next_cue.get('is_moving_shot', False), label=f"Early Prep: {scene}")
                prepped_cams.add(next_cam)

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
            
            # Phase 1: SETTLING
            self.phase = "SETTLING"
            self._send_camera_action(cam, action, cue.get('is_moving_shot', False), label=f"Cue: {scene} (Settling)")
            
            self.timer_duration = float(cue.get("settle_time_sec", 4.0))
            self.timer_elapsed = 0.0
            while self.timer_elapsed < self.timer_duration and self.is_running and not self.skip_flag:
                time.sleep(0.1)
                self.timer_elapsed += 0.1
            
            if not self.is_running: break
            if self.skip_flag: 
                self.skip_flag = False
                continue 
            
            # Phase 2: LIVE ON AIR
            self.phase = "LIVE ON AIR"
            
            if self.obs and self.obs.connected and scene != "Unknown": 
                self.obs.set_scene(scene)
                
                verify_time = 0.0
                verified = False
                while verify_time < 1.5 and self.is_running and not self.skip_flag:
                    if self.current_scene_cb and self.current_scene_cb() == scene:
                        verified = True
                        break
                    time.sleep(0.1)
                    verify_time += 0.1
                    
                if not verified and not self.skip_flag:
                    self.tour_error = f"ABORTED: OBS failed to transition to '{scene}'"
                    self.stop_tour()
                    continue
            
            self._send_camera_action(cam, "status_only", False, label=f"Cue: {scene} (LIVE ON AIR)")
                
            self.timer_duration = float(cue.get("live_duration_sec", 10.0))
            self.timer_elapsed = 0.0
            
            prepped_off_air = False
            
            # Combined Timer Loop: Handles the delay, the off-air prep, and the external abort scan all at once
            while self.timer_elapsed < self.timer_duration and self.is_running and not self.skip_flag:
                
                # External Abort Scan
                if self.obs and self.obs.connected and self.current_scene_cb and scene != "Unknown":
                    if self.current_scene_cb() != scene:
                        self.tour_error = "ABORTED: External OBS scene change detected."
                        self.stop_tour()
                        break
                
                # Wait 1 full second into the Live shot before moving the off-air cameras
                if not prepped_off_air and self.timer_elapsed >= 1.0:
                    self._prep_off_air_cameras(self.current_cue_idx)
                    prepped_off_air = True
                        
                time.sleep(0.1)
                self.timer_elapsed += 0.1
            
            if not self.is_running: break
            if self.skip_flag: 
                self.skip_flag = False
                continue 
            
            self.current_cue_idx = (self.current_cue_idx + 1) % len(self.cues)