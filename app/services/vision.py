import cv2
import os
import threading
import time

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer|flags;low_delay"

class VisionTracker:
    def __init__(self, source=0):
        self.source = source
        
        if isinstance(self.source, str) and self.source.startswith("rtsp"):
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        else:
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
            
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.obj_tracker = None
        self.tracking_locked = False
        self.target_hist = None
        self.lost_frames = 0
        
        self.pending_target = None
        self.pending_clear = False
        
        self.latest_frame = None
        self.ret = False
        self.running = True
        
        if self.cap.isOpened():
            self.thread = threading.Thread(target=self._update_frames, daemon=True)
            self.thread.start()

    def _update_frames(self):
        while self.running:
            if self.cap.isOpened():
                self.ret, frame = self.cap.read()
                if self.ret:
                    self.latest_frame = cv2.resize(frame, (640, 360))
                else: time.sleep(0.033)
            else:
                time.sleep(0.033)

    def stop(self):
        self.running = False
        if hasattr(self, 'thread'): self.thread.join(timeout=1.0)
        if self.cap.isOpened(): self.cap.release()

    def _create_tracker(self):
        try: return cv2.TrackerCSRT_create()
        except AttributeError:
            try: return cv2.TrackerKCF_create()
            except AttributeError: return cv2.TrackerMIL_create()

    def set_manual_target(self, x_pct, y_pct):
        self.pending_target = (x_pct, y_pct)

    def clear_target(self):
        self.pending_clear = True

    def _get_color_histogram(self, frame, bbox):
        x, y, w, h = [int(v) for v in bbox]
        h_f, w_f, _ = frame.shape
        x = max(0, x); y = max(0, y)
        w = min(w, w_f - x); h = min(h, h_f - y)
        if w <= 0 or h <= 0: return None
        
        roi = frame[y:y+h, x:x+w]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist

    def get_frame(self, deadband=60):
        if not self.ret or self.latest_frame is None:
            return False, None, 0, 0, "STANDBY"

        frame = self.latest_frame.copy()
        height, width, _ = frame.shape
        center_x = width // 2
        center_y = int(height * 0.33)
        err_x, err_y = 0, 0
        status = "STANDBY"
        
        if self.pending_clear:
            self.tracking_locked = False
            self.obj_tracker = None
            self.target_hist = None
            self.lost_frames = 0
            self.pending_clear = False
            
        if self.pending_target is not None:
            px_pct, py_pct = self.pending_target
            self.pending_target = None 
            click_x = int(px_pct * width)
            click_y = int(py_pct * height)
            
            bw, bh = 100, 140
            nx = max(0, click_x - (bw // 2))
            ny = max(0, click_y - (bh // 2))
            initial_bbox = (nx, ny, bw, bh)
                
            self.obj_tracker = self._create_tracker()
            self.obj_tracker.init(frame, initial_bbox)
            self.target_hist = self._get_color_histogram(frame, initial_bbox)
            self.tracking_locked = True
            self.lost_frames = 0

        if self.tracking_locked and self.obj_tracker is not None:
            try:
                success, bbox = self.obj_tracker.update(frame)
                if success:
                    x, y, w, h = [int(v) for v in bbox]
                    tx = x + (w // 2)
                    ty = y + (h // 2)
                    err_x = tx - center_x
                    err_y = ty - center_y
                    
                    if self.lost_frames % 10 == 0:
                        new_hist = self._get_color_histogram(frame, bbox)
                        if new_hist is not None: self.target_hist = new_hist

                    # Target Box & Radar Tether Line
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)
                    cv2.line(frame, (center_x, center_y), (tx, ty), (0, 255, 255), 1)
                    cv2.circle(frame, (tx, ty), 4, (0, 255, 255), -1)
                    cv2.putText(frame, "LOCKED", (x, max(15, y-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                    status = "LOCKED"
                    self.lost_frames = 0
                else:
                    self.tracking_locked = False
                    self.obj_tracker = None
                    self.lost_frames = 1
            except Exception:
                self.tracking_locked = False
                self.obj_tracker = None
                self.lost_frames = 1
                
        if not self.tracking_locked and 0 < self.lost_frames < 30:
            status = "COASTING"
            self.lost_frames += 1
            
            if self.target_hist is not None:
                best_match = 0
                best_box = None
                step = 40
                bw, bh = 100, 140
                
                for sy in range(0, height - bh, step):
                    for sx in range(0, width - bw, step):
                        cand_box = (sx, sy, bw, bh)
                        cand_hist = self._get_color_histogram(frame, cand_box)
                        if cand_hist is not None:
                            score = cv2.compareHist(self.target_hist, cand_hist, cv2.HISTCMP_CORREL)
                            if score > best_match:
                                best_match = score
                                best_box = cand_box
                
                if best_match > 0.65 and best_box is not None:
                    self.obj_tracker = self._create_tracker()
                    self.obj_tracker.init(frame, best_box)
                    self.tracking_locked = True
                    self.lost_frames = 0
                    status = "LOCKED"
                    cv2.putText(frame, "RE-ACQUIRED", (best_box[0], best_box[1]-5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
                    
        elif self.lost_frames >= 30:
            self.lost_frames = 0
            self.target_hist = None
            status = "STANDBY"

        # --- HUD RADAR OVERLAY ---
        # Crosshairs
        cv2.line(frame, (center_x, 0), (center_x, height), (100, 100, 100), 1)
        cv2.line(frame, (0, center_y), (width, center_y), (100, 100, 100), 1)
        # Deadband Circle
        cv2.circle(frame, (center_x, center_y), int(deadband), (92, 184, 92), 1)
        cv2.circle(frame, (center_x, center_y), 3, (0, 0, 255), -1)
        
        # Telemetry Banner on bottom-left of video
        cv2.rectangle(frame, (5, height - 28), (275, height - 5), (0, 0, 0), -1)
        hud_text = f"X Err: {err_x} | Y Err: {err_y} | DB: {int(deadband)}px"
        cv2.putText(frame, hud_text, (10, height - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (222, 192, 91), 1)

        return True, frame, err_x, err_y, status