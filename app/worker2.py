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
    "error_x": 0, "error_y": 0,
    "p": 0.03, "i": 0.00, "d": 0.02, "deadband": 60, "loop_delay": 33,
    "cam_ip": "192.168.1.101", "cam_port": 5678, "cam_source": "1", 
    "last_command": "Idle"
}

latest_frame = None
cam = None  

class PIDController:
    def __init__(self, p=0.03, i=0.0, d=0.01, deadband=60):
        self.Kp = p; self.Ki = i; self.Kd = d; self.deadband = deadband
        self.prev_error = 0; self.integral = 0
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
    
    while True:
        if worker_state["cam_source"] != current_source:
            current_source = worker_state["cam_source"]
            if hasattr(tracker, 'stop'): tracker.stop()
            elif hasattr(tracker, 'cap'): tracker.cap.release()
                
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
            
            if worker_state["joystick_active"]:
                was_tracking = False
                time.sleep(worker_state["loop_delay"] / 1000.0)
                continue 
                
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
                    if direction == "stop": worker_state["last_command"] = "Auto: Locked on target"
                    else: worker_state["last_command"] = f"Auto: {direction} (Pan: {p_speed}, Tilt: {t_speed})"
            else:
                if was_tracking:
                    if cam: cam.move(0, 0, "stop")
                    worker_state["last_command"] = "Auto: Standby"
                    was_tracking = False
        else:
            latest_frame = None
            worker_state["last_command"] = "System: Video Stream Offline or Unreachable"
                
        time.sleep(worker_state["loop_delay"] / 1000.0)

def generate_frames():
    global latest_frame
    while True:
        if latest_frame is not None:
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            if ret: yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.033)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cam
    cam = PTZCamera(worker_state["cam_ip"], port=worker_state["cam_port"])
    threading.Thread(target=vision_loop, daemon=True).start()
    yield

app = FastAPI(title="PTZ Worker 2", lifespan=lifespan)

@app.get("/api/state")
def get_state(): return worker_state

@app.get("/api/video_feed")
def video_feed(): return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/api/toggle")
def toggle_tracking():
    worker_state["tracking_active"] = not worker_state["tracking_active"]
    if not worker_state["tracking_active"]: worker_state["last_command"] = "System: Tracking Disabled"
    return {"active": worker_state["tracking_active"]}

@app.post("/api/config")
async def update_config(request: Request):
    global cam
    data = await request.json()
    new_ip = data.get("cam_ip", worker_state["cam_ip"])
    new_port = int(data.get("cam_port", worker_state["cam_port"]))
    
    if new_ip != worker_state["cam_ip"] or new_port != worker_state["cam_port"]:
        worker_state["cam_ip"] = new_ip
        worker_state["cam_port"] = new_port
        cam = PTZCamera(new_ip, port=new_port)
        worker_state["last_command"] = f"System: Reconnected to {new_ip}:{new_port}"

    for key in ["p", "i", "d", "deadband", "loop_delay", "cam_source"]:
        if key in data:
            if key in ["p", "i", "d"]: worker_state[key] = float(data[key])
            elif key in ["deadband", "loop_delay"]: worker_state[key] = int(data[key])
            else: worker_state[key] = str(data[key])
    return {"status": "success"}

@app.post("/api/ptz/move")
async def ptz_move(request: Request):
    global cam
    data = await request.json()
    direction = data.get("direction", "stop")
    if direction == "stop":
        worker_state["joystick_active"] = False
        if cam: cam.move(0, 0, "stop")
        worker_state["last_command"] = "Manual: Stop"
    else:
        worker_state["joystick_active"] = True
        if cam: cam.move(10, 10, direction)
        worker_state["last_command"] = f"Manual: Jog {direction}"
    return {"status": "success"}

@app.post("/api/ptz/zoom")
async def ptz_zoom(request: Request):
    global cam
    data = await request.json()
    direction = data.get("direction", "stop")
    if direction == "stop":
        worker_state["joystick_active"] = False
        if cam: cam.zoom(0, "stop")
        worker_state["last_command"] = "Manual: Zoom Stop"
    else:
        worker_state["joystick_active"] = True
        if cam: cam.zoom(4, direction)
        worker_state["last_command"] = f"Manual: Zoom {direction}"
    return {"status": "success"}

@app.post("/api/ptz/save_preset")
async def ptz_save_preset(request: Request):
    global cam
    data = await request.json()
    preset = int(data.get("preset", 1))
    if cam and hasattr(cam, 'save_preset'):
        cam.save_preset(preset)
        worker_state["last_command"] = f"System: Saved to Preset {preset}"
    return {"status": "success"}

@app.post("/api/ptz/recall_preset")
async def ptz_recall_preset(request: Request):
    global cam
    data = await request.json()
    preset = int(data.get("preset", 1))
    if cam and hasattr(cam, 'recall_preset'):
        cam.recall_preset(preset)
        worker_state["last_command"] = f"System: Recalled Preset {preset}"
    return {"status": "success"}

@app.post("/api/target/set")
async def set_target(request: Request):
    data = await request.json()
    if 'tracker' in globals() and hasattr(tracker, 'set_manual_target'):
        tracker.set_manual_target(data.get("x_pct"), data.get("y_pct"))
        worker_state["last_command"] = "System: Target Manually Locked"
    return {"status": "success"}

@app.post("/api/target/clear")
def clear_target():
    if 'tracker' in globals() and hasattr(tracker, 'clear_target'):
        tracker.clear_target()
        worker_state["last_command"] = "System: Target Cleared"
    return {"status": "success"}

@app.post("/api/action")
async def execute_director_action(request: Request):
    global cam
    data = await request.json()
    action = data.get("action", "stop")
    label = data.get("label", "")
    
    if action == "status_only":
        worker_state["last_command"] = f"Director: {label}"
        return {"status": "success"}
    if action == "track_face":
        worker_state["tracking_active"] = True
        worker_state["last_command"] = f"Director: {label} [Auto-Track]" if label else "Director: Engaging Auto-Track"
    elif action.startswith("preset_"):
        worker_state["tracking_active"] = False
        try:
            preset_num = int(action.split("_")[1])
            if cam: cam.recall_preset(preset_num)
            worker_state["last_command"] = f"Director: {label} [Preset {preset_num}]" if label else f"Director: Recalled Preset {preset_num}"
        except: pass
    else:
        worker_state["tracking_active"] = False
        if cam: cam.move(0, 0, "stop")
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run("app.worker2:app", host="0.0.0.0", port=8002, reload=True)