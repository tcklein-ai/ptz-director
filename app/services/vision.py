import cv2
import os
import threading
import time

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer|flags;low_delay"

class VisionTracker:
    def __init__(self, source=0):
        self.source = source
        self.cap = cv2.VideoCapture(self.source)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.obj_tracker = None
        self.tracking_locked = False
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
                    self.latest_frame = frame
            else:
                time.sleep(0.033)

    def stop(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        if self.cap.isOpened():
            self.cap.release()

    def _create_tracker(self):
        try: return cv2.TrackerCSRT_create()
        except AttributeError:
            try: return cv2.TrackerKCF_create()
            except AttributeError: return cv2.TrackerMIL_create()

    def set_manual_target(self, x_pct, y_pct):
        # NEW: Safely queues the UI click instead of hijacking the thread
        self.pending_target = (x_pct, y_pct)

    def clear_target(self):
        self.pending_clear = True

    def get_frame(self):
        if not self.ret or self.latest_frame is None:
            return False, None, 0, 0

        frame = self.latest_frame.copy()
        height, width, _ = frame.shape
        center_x = width // 2
        center_y = int(height * 0.33)
        err_x, err_y = 0, 0
        
        # --- Safely process queued UI commands on the correct thread ---
        if self.pending_clear:
            self.tracking_locked = False
            self.obj_tracker = None
            self.pending_clear = False
            
        if self.pending_target is not None:
            x_pct, y_pct = self.pending_target
            self.pending_target = None 
            
            cx = int(x_pct * width)
            cy = int(y_pct * height)
            
            bw, bh = 150, 200
            nx = max(0, cx - (bw // 2))
            ny = max(0, cy - (bh // 2))
            
            self.obj_tracker = self._create_tracker()
            self.obj_tracker.init(frame, (nx, ny, bw, bh))
            self.tracking_locked = True
        
        # --- Run the Math ---
        if self.tracking_locked and self.obj_tracker is not None:
            try:
                success, bbox = self.obj_tracker.update(frame)
                if success:
                    x, y, w, h = [int(v) for v in bbox]
                    err_x = (x + (w // 2)) - center_x
                    err_y = (y + (h // 2)) - center_y
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)
                    cv2.putText(frame, "LOCKED (CSRT)", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                else:
                    self.tracking_locked = False
                    self.obj_tracker = None
            except Exception as e:
                print(f"[VISION] Tracker crash averted: {e}")
                self.tracking_locked = False
                self.obj_tracker = None

        cv2.line(frame, (center_x, 0), (center_x, height), (255, 0, 0), 1)
        cv2.line(frame, (0, center_y), (width, center_y), (255, 0, 0), 1)
        cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

        return True, frame, err_x, err_y