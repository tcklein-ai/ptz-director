import uvicorn
import threading
import time
import cv2 
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager

from app.services.vision import VisionTracker
from app.services.visca import PTZCamera

worker_state = {
    "tracking_active": False,
    "joystick_active": False,
    "error_x": 0,
    "error_y": 0,
    "p": 0.05, 
    "i": 0.00, 
    "d": 0.02, 
    "deadband": 40, 
    "loop_delay": 50,
    "cam_ip": "192.168.1.100",
    "cam_port": 1259,
    "cam_source": "0", 
    "last_command": "Idle"
}

latest_frame = None
cam = None  

class PIDController:
    def __init__(self, p=0.05, i=0.0, d=0.01, deadband=30):
        self.Kp = p
        self.Ki = i
        self.Kd = d
        self.deadband = deadband
        self.prev_error = 0
        self.integral = 0
        
    def update(self, error, dt):
        if abs(error) < self.deadband:
            self.integral = 0
            return 0
        self.integral += error * dt
        derivative = (error - self.prev_error) / dt
        self.prev_error = error
        return (self.Kp * error) + (self.Ki * self.integral) + (self.Kd * derivative)

def vision_loop():
    global latest_frame, cam
    
    current_source = worker_state["cam_source"]
    source_val = int(current_source) if str(current_source).isdigit() else current_source
    tracker = VisionTracker(source_val) 
    
    pan_pid = PIDController()
    tilt_pid = PIDController()
    last_time = time.time()
    was_tracking = False 
    
    print("[WORKER 1] Vision loop running on separate core.")
    
    while True:
        # Safely shut down the old tracker thread before swapping video sources
        if worker_state["cam_source"] != current_source:
            current_source = worker_state["cam_source"]
            if hasattr(tracker, 'stop'): 
                tracker.stop()
            elif hasattr(tracker, 'cap'): 
                tracker.cap.release()
                
            source_val = int(current_source) if str(current_source).isdigit() else current_source
            tracker = VisionTracker(source_val)
            worker_state["last_command"] = f"System: Bound to Video Device {current_source}"
        
        current_time = time.time()
        dt = current_time - last_time
        last_time = current_time

        success, frame, err_x, err_y = tracker.get_frame()
        
        if success:
            latest_frame = frame.copy()
            worker_state["error_x"] = int(err_x)
            worker_state["error_y"] = int(err_y)
            
            # YIELD TO HUMAN JOYSTICK
            if worker_state["joystick_active"]:
                was_tracking = False
                time.sleep(worker_state["loop_delay"] / 1000.0)
                continue 
                
            # RUN AUTONOMOUS MATH
            if worker_state["tracking_active"]:
                was_tracking = True
                pan_pid.Kp = tilt_pid.Kp = worker_state["p"]
                pan_pid.Ki = tilt_pid.Ki = worker_state["i"]
                pan_pid.Kd = tilt_pid.Kd = worker_state["d"]
                pan_pid.deadband = tilt_pid.deadband = worker_state["deadband"]

                pan_output = pan_pid.update(err_x, dt)
                tilt_output = tilt_pid.update(err_y, dt)
                
                dir_parts = []
                if tilt_output > 0: dir_parts.append("down")
                elif tilt_output < 0: dir_parts.append("up")
                if pan_output > 0: dir_parts.append("right")
                elif pan_output < 0: dir_parts.append("left")
                
                direction = "_".join(dir_parts) if dir_parts else "stop"
                p_speed = 0 if direction == "stop" else min(24, max(1, int(abs(pan_output))))
                t_speed = 0 if direction == "stop" else min(20, max(1, int(abs(tilt_output))))
                
                if cam: 
                    cam.move(p_speed, t_speed, direction)
                    if direction == "stop": 
                        worker_state["last_command"] = "Auto: Locked on target"
                    else: