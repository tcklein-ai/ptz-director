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
        """Initializes the CSRT tracker based on a UI mouse click."""
        if self.latest_frame is None: return
        
        h, w, _ = self.latest_frame.shape
        cx = int(x_pct * w)
        cy = int(y_pct * h)
        
        # Create a 150x200 pixel box centered on the click (standard torso/head size at 50ft)
        bw, bh = 150, 200
        nx = max(0, cx - (bw // 2))
        ny = max(0, cy - (bh // 2))
        
        self.obj_tracker = self._create_tracker()
        self.obj_tracker.init(self.latest_frame, (nx, ny, bw, bh))
        self.tracking_locked = True

    def clear_target(self):
        self.tracking_locked = False
        self.obj_tracker = None

    def get_frame(self):
        if not self.ret or self.latest_frame is None:
            return False, None, 0, 0

        frame = self.latest_frame.copy()
        height, width, _ = frame.shape
        center_x = width // 2
        center_y = int(height * 0.33)
        err_x, err_y = 0, 0
        
        if self.tracking_locked and self.obj_tracker is not None:
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

        cv2.line(frame, (center_x, 0), (center_x, height), (255, 0, 0), 1)
        cv2.line(frame, (0, center_y), (width, center_y), (255, 0, 0), 1)
        cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

        return True, frame, err_x, err_y