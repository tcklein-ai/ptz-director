import cv2
import os
import urllib.request

class VisionTracker:
    def __init__(self, camera_source=0):
        """Initializes the webcam and the Haar Cascade face detector."""
        self.cap = cv2.VideoCapture(camera_source)
        
        # Safely construct the path for Windows environments
        cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        
        # Bulletproof fallback: Download the XML if it is missing from the pip install
        if not os.path.exists(cascade_path):
            print("[VISION] Local cascade not found. Downloading from OpenCV GitHub...")
            url = "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml"
            cascade_path = "haarcascade_frontalface_default.xml"
            if not os.path.exists(cascade_path):
                urllib.request.urlretrieve(url, cascade_path)
                
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

    def get_frame(self):
        """Reads a frame, calculates the error from the top-third setpoint, and returns the data."""
        success, frame = self.cap.read()
        if not success:
            return False, None, 0, 0

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)

        height, width, _ = frame.shape
        
        # X target is center, Y target is top-third line
        target_x = width // 2
        target_y = height // 3 

        err_x = 0
        err_y = 0

        cv2.line(frame, (target_x, 0), (target_x, height), (255, 0, 0), 1)
        cv2.line(frame, (0, target_y), (width, target_y), (255, 0, 0), 1)

        if len(faces) > 0:
            (x, y, w, h) = faces[0]
            face_center_x = x + (w // 2)
            face_center_y = y + (h // 2)

            err_x = face_center_x - target_x
            err_y = face_center_y - target_y

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (face_center_x, face_center_y), 5, (0, 0, 255), -1)
            cv2.line(frame, (target_x, target_y), (face_center_x, face_center_y), (0, 255, 255), 2)

        return True, frame, err_x, err_y

    def release(self):
        self.cap.release()