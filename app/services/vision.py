import cv2
import os
import threading
import time
import urllib.request

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer|flags;low_delay"

class VisionTracker:
    def __init__(self, source=0):
        self.source = source
        
        if isinstance(self.source, str) and self.source.startswith("rtsp"):
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        else:
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
            
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Load Face Cascade for multi-target detection
        cascade_name = 'haarcascade_frontalface_default.xml'
        local_path = os.path.join(os.getcwd(), cascade_name)
        default_path = os.path.join(cv2.data.haarcascades, cascade_name)
        
        if os.path.exists(local_path): self.face_cascade = cv2.CascadeClassifier(local_path)
        elif os.path.exists(default_path): self.face_cascade = cv2.CascadeClassifier(default_path)
        else:
            try:
                urllib.request.urlretrieve(f"https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/{cascade_name}", local_path)
                self.face_cascade = cv2.CascadeClassifier(local_path)
            except Exception: self.face_cascade = cv2.CascadeClassifier()
        
        self.obj_tracker = None
        self.tracking_locked = False
        self.detected_candidates = [] # Stores current green boxes
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
                if self.ret: self.latest_frame = frame
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

    def get_frame(self):
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
            self.lost_frames = 0
            self.pending_clear = False
            
        # 1. Continuously detect all available faces for green overlays
        self.detected_candidates = []
        if not self.face_cascade.empty():
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            for (x, y, w, h) in faces:
                expand = int(w * 0.3)
                nx = max(0, x - expand)
                ny = max(0, y - expand)
                nw = min(width - nx, w + (expand * 2))
                nh = min(height - ny, h + (expand * 2))
                self.detected_candidates.append((nx, ny, nw, nh))

        # 2. Handle Mouse Click Selection (Check if click collides with a green box)
        if self.pending_target is not None:
            px_pct, py_pct = self.pending_target
            self.pending_target = None 
            click_x = int(px_pct * width)
            click_y = int(py_pct * height)
            
            selected_box = None
            # Check collision with detected green candidates first
            for (nx, ny, nw, nh) in self.detected_candidates:
                if nx <= click_x <= nx + nw and ny <= click_y <= ny + nh:
                    selected_box = (nx, ny, nw, nh)
                    break
            
            # If click didn't land on a detected face, drop a default box around the click
            if selected_box is None:
                bw, bh = 150, 200
                nx = max(0, click_x - (bw // 2))
                ny = max(0, click_y - (bh // 2))
                selected_box = (nx, ny, bw, bh)
                
            self.obj_tracker = self._create_tracker()
            self.obj_tracker.init(frame, selected_box)
            self.tracking_locked = True
            self.lost_frames = 0

        # 3. Draw Green Boxes for all available choices
        if not self.tracking_locked:
            for (nx, ny, nw, nh) in self.detected_candidates:
                cv2.rectangle(frame, (nx, ny), (nx+nw, ny+nh), (0, 255, 0), 2)
                cv2.putText(frame, "TARGET", (nx, ny-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        # 4. Active Yellow Lock Tracking (CSRT)
        if self.tracking_locked and self.obj_tracker is not None:
            try:
                success, bbox = self.obj_tracker.update(frame)
                if success:
                    x, y, w, h = [int(v) for v in bbox]
                    err_x = (x + (w // 2)) - center_x
                    err_y = (y + (h // 2)) - center_y
                    
                    # Active target rendered in Yellow
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 255), 2)
                    cv2.putText(frame, "LOCKED (SELECTED)", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                    status = "LOCKED"
                    self.lost_frames = 0
                else:
                    self.tracking_locked = False
                    self.obj_tracker = None
                    self.lost_frames = 1
            except Exception as e:
                self.tracking_locked = False
                self.obj_tracker = None
                self.lost_frames = 1
                
        # 5. Coasting & Search fallback if active lock is lost
        if not self.tracking_locked and 0 < self.lost_frames < 45:
            status = "COASTING"
            if len(self.detected_candidates) > 0:
                # Re-acquire nearest candidate automatically
                nx, ny, nw, nh = self.detected_candidates[0]
                self.obj_tracker = self._create_tracker()
                self.obj_tracker.init(frame, (nx, ny, nw, nh))
                self.tracking_locked = True
                self.lost_frames = 0
                status = "LOCKED"
            else:
                self.lost_frames += 1
                cv2.putText(frame, "SEARCHING...", (width//2 - 60, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
        elif self.lost_frames >= 45:
            self.lost_frames = 0
            status = "STANDBY"

        cv2.line(frame, (center_x, 0), (center_x, height), (255, 0, 0), 1)
        cv2.line(frame, (0, center_y), (width, center_y), (255, 0, 0), 1)
        cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

        return True, frame, err_x, err_y, status