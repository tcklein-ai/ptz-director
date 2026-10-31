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
    "joystick_active": False, # Suspends tracking math when human is driving
    "error_x": 0,
    "error_y": 0,
    "p": 0.05,
    "i": 0.00,
    "d": 0.02,
    "deadband": 40,
    "loop_delay": 50,
}

latest_frame = None
cam = None  # Made global so HTTP endpoints can access the hardware

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
    tracker = VisionTracker(0) 
    pan_pid = PIDController()
    tilt_pid = PIDController()
    last_time = time.time()
    
    # We use this to prevent spamming "stop" commands to the camera over UDP
    was_tracking = False 
    
    print("[WORKER 1] Vision loop running on separate core.")
    
    while True:
        current_time = time.time()
        dt = current_time - last_time
        last_time = current_time

        success, frame, err_x, err_y = tracker.get_frame()
        
        if success:
            latest_frame = frame.copy()
            worker_state["error_x"] = int(err_x)
            worker_state["error_y"] = int(err_y)
            
            # 1. YIELD TO HUMAN JOYSTICK
            if worker_state["joystick_active"]:
                was_tracking = False
                time.sleep(worker_state["loop_delay"] / 1000.0)
                continue # Skip the PID math entirely
                
            # 2. RUN AUTONOMOUS MATH
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
                
                if cam: cam.move(p_speed, t_speed, direction)
            
            # 3. CLEAN STANDBY
            else:
                if was_tracking:
                    if cam: cam.move(0, 0, "stop")
                    was_tracking = False
                
        time.sleep(worker_state["loop_delay"] / 1000.0)

def generate_frames():
    global latest_frame
    while True:
        if latest_frame is not None:
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.05) 

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cam
    cam = PTZCamera("192.168.1.100", port=1259)
    threading.Thread(target=vision_loop, daemon=True).start()
    yield
    # No explicit camera close needed for connectionless UDP

app = FastAPI(title="PTZ Worker 1", lifespan=lifespan)

@app.get("/api/state")
def get_state(): 
    return worker_state

@app.get("/api/video_feed")
def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/api/toggle")
def toggle_tracking():
    worker_state["tracking_active"] = not worker_state["tracking_active"]
    return {"active": worker_state["tracking_active"]}

@app.post("/api/tune")
async def tune_pid(request: Request):
    data = await request.json()
    for key in ["p", "i", "d", "deadband", "loop_delay"]:
        if key in data: 
            worker_state[key] = float(data[key]) if key in ["p", "i", "d"] else int(data[key])
    return {"status": "success"}

# ==========================================
# NEW: HARDWARE COMMAND ENDPOINTS
# ==========================================

@app.post("/api/ptz/move")
async def ptz_move(request: Request):
    """Handles manual joystick jogging from the UI."""
    global cam
    data = await request.json()
    direction = data.get("direction", "stop")
    
    if direction == "stop":
        worker_state["joystick_active"] = False
        if cam: cam.move(0, 0, "stop")
    else:
        worker_state["joystick_active"] = True
        # Using a flat mid-speed (10, 10) for manual jogging
        if cam: cam.move(10, 10, direction)
        
    return {"status": "success"}

@app.post("/api/ptz/save_preset")
async def ptz_save_preset(request: Request):
    """Commands the hardware to save current position to memory."""
    global cam
    data = await request.json()
    preset = int(data.get("preset", 1))
    
    if cam and hasattr(cam, 'save_preset'):
        cam.save_preset(preset)
    else:
        print("[WORKER] Skipping save: save_preset() not implemented in visca.py")
        
    return {"status": "success"}

@app.post("/api/action")
async def execute_director_action(request: Request):
    """Executes commands fired from the Automated Scene Tour Director."""
    global cam
    data = await request.json()
    action = data.get("action", "stop")
    allow_movement = data.get("allow_movement_on_program", False)

    print(f"\n[WORKER] Received Director Action: {action}")
    
    if action == "track_face":
        worker_state["tracking_active"] = True
    elif action.startswith("preset_"):
        worker_state["tracking_active"] = False
        try:
            preset_num = int(action.split("_")[1])
            if cam and hasattr(cam, 'recall_preset'):
                cam.recall_preset(preset_num)
            else:
                print("[WORKER] Skipping recall: recall_preset() not implemented in visca.py")
        except Exception as e:
            print(f"[WORKER] Error parsing preset: {e}")
    else:
        # Default safety: Turn off tracking and hit the brakes
        worker_state["tracking_active"] = False
        if cam: cam.move(0, 0, "stop")
        
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run("app.worker:app", host="0.0.0.0", port=8001, reload=True)