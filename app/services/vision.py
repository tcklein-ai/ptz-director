import cv2
import os
import urllib.request
import threading
import time

# Force FFmpeg to drop buffers and prioritize real-time over smoothness
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer|flags;low_delay"

class VisionTracker:
    def __init__(self, source=0):
        self.source = source
        self.cap = cv2.VideoCapture(self.source)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # --- Haar Cascade Setup ---
        cascade_name = 'haarcascade_frontalface_default.xml'
        local_path = os.path.join(os.getcwd(), cascade_name)
        default_path = os.path.join(cv2.data.haarcascades, cascade_name)
        
        if os.path.exists(local_path):
            self.face_cascade = cv2.CascadeClassifier(local_path)
        elif os.path.exists(default_path):
            self.face_cascade = cv2.CascadeClassifier(default_path)
        else:
            try:
                urllib.request.urlretrieve(f"https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/{cascade_name}", local_path)
                self.face_cascade = cv2.CascadeClassifier(local_path)
            except Exception as e:
                self.face_cascade = cv2.CascadeClassifier() 

        if self.face_cascade.empty():
            print("[VISION] FATAL: Face cascade failed to load. Tracking disabled.")

        # --- NEW: Threaded Frame Grabber ---
        self.latest_frame = None
        self.ret = False
        self.running = True
        
        if self.cap.isOpened():
            print(f"[VISION] Connected to {source}. Starting frame-grabber thread...")
            self.thread = threading.Thread(target=self._update_frames, daemon=True)
            self.thread.start()
        else:
            print(f"[VISION] Failed to connect to video source: {source}")

    def _update_frames(self):
        """Runs in the background, constantly pulling frames to empty the network buffer."""
        while self.running:
            if self.cap.isOpened():
                # We do not use time.sleep here; we want it to run as fast as the network allows
                self.ret, frame = self.cap.read()
                if self.ret:
                    self.latest_frame = frame
            else:
                time.sleep(0.1)

    def stop(self):
        """Safely kills the background thread when changing cameras."""
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        if self.cap.isOpened():
            self.cap.release()

    def get_frame(self):
        """Math loop calls this to instantly get the freshest frame without waiting."""
        if not self.ret or self.latest_frame is None:
            return False, None, 0, 0

        # Create a copy so the background thread doesn't overwrite it while we are drawing on it
        frame = self.latest_frame.copy()
        
        height, width, _ = frame.shape
        center_x = width // 2
        center_y = int(height * 0.33)
        
        err_x = 0
        err_y = 0
        
        if not self.face_cascade.empty():
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            
            if len(faces) > 0:
                (x, y, w, h) = faces[0]
                target_x = x + (w // 2)
                target_y = y + (h // 2)
                
                err_x = target_x - center_x
                err_y = target_y - center_y
                
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # Draw the target crosshairs
        cv2.line(frame, (center_x, 0), (center_x, height), (255, 0, 0), 1)
        cv2.line(frame, (0, center_y), (width, center_y), (255, 0, 0), 1)
        cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

        return True, frame, err_x, err_y