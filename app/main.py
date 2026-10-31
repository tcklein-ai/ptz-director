import uvicorn
import json
import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.services.obs_link import OBSManager

CONFIG_FILE = "config.json"
TOUR_FILE = "tour_config.json"
WORKER_1_URL = "http://127.0.0.1:8001"

global_state = {
    "current_scene": "Unknown",
    "obs_host": "localhost",
    "obs_port": 4455,
    "obs_password": "",
    "obs_connected": False,
    "p": 0.05, "i": 0.00, "d": 0.02, "deadband": 40, "loop_delay": 50,
    
    # These are populated by polling the worker
    "tracking_active": False,
    "error_x": 0,
    "error_y": 0,
}

obs_manager = None
templates = Jinja2Templates(directory="app/templates")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                for k in ["p", "i", "d", "deadband", "loop_delay", "obs_host", "obs_port", "obs_password"]:
                    if k in saved: global_state[k] = saved[k]
        except Exception as e: 
            print(f"Error loading config: {e}")

def save_config():
    data = {k: global_state[k] for k in ["p", "i", "d", "deadband", "loop_delay", "obs_host", "obs_port", "obs_password"]}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def push_tuning_to_worker():
    payload = {k: global_state[k] for k in ["p", "i", "d", "deadband", "loop_delay"]}
    try:
        requests.post(f"{WORKER_1_URL}/api/tune", json=payload, timeout=1.0)
    except requests.exceptions.RequestException:
        pass

def handle_scene_change(scene_name: str):
    global_state["current_scene"] = scene_name
    print(f"[OBS] Transitioned to: {scene_name}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    
    global obs_manager
    obs_manager = OBSManager(
        host=global_state["obs_host"], port=global_state["obs_port"], 
        password=global_state["obs_password"], on_scene_change=handle_scene_change
    )
    global_state["obs_connected"] = obs_manager.connected
    
    push_tuning_to_worker()
    yield
    if obs_manager: 
        obs_manager.disconnect()

app = FastAPI(title="PTZ Director Hub", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

@app.get("/api/toggle")
def toggle_tracking():
    try:
        response = requests.post(f"{WORKER_1_URL}/api/toggle", timeout=1.0)
        global_state["tracking_active"] = response.json().get("active", False)
    except:
        pass
    return {"active": global_state["tracking_active"]}

@app.get("/api/state")
def get_state():
    try:
        res = requests.get(f"{WORKER_1_URL}/api/state", timeout=0.2).json()
        global_state["error_x"] = res.get("error_x", 0)
        global_state["error_y"] = res.get("error_y", 0)
        global_state["tracking_active"] = res.get("tracking_active", False)
    except:
        global_state["error_x"] = 0
        global_state["error_y"] = 0
        
    return global_state

@app.post("/api/obs")
async def config_obs(request: Request):
    global obs_manager
    data = await request.json()
    for k in ["host", "port", "password"]: 
        if k in data: global_state[f"obs_{k}"] = data[k]
    
    global_state["obs_port"] = int(global_state["obs_port"])
    save_config()
    
    if obs_manager:
        success = obs_manager.reconnect(global_state["obs_host"], global_state["obs_port"], global_state["obs_password"])
        global_state["obs_connected"] = success
    return {"status": "success"}

@app.post("/api/tune")
async def tune_pid(request: Request):
    data = await request.json()
    for k in ["p", "i", "d", "deadband", "loop_delay"]:
        if k in data:
            global_state[k] = float(data[k]) if k in ["p", "i", "d"] else int(data[k])
            
    save_config()
    push_tuning_to_worker()
    return {"status": "success"}

@app.get("/api/video_feed")
def video_feed():
    """Proxies the MJPEG stream from the Camera Worker to the Web UI."""
    def generate():
        try:
            with requests.get(f"{WORKER_1_URL}/api/video_feed", stream=True, timeout=5.0) as r:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except requests.exceptions.RequestException:
            pass
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


# ==========================================
# NEW: VIRTUAL DIRECTOR & JOYSTICK ROUTES
# ==========================================

@app.get("/api/tour")
def get_tour():
    """Reads the current sequence from the show file."""
    if os.path.exists(TOUR_FILE):
        with open(TOUR_FILE, "r") as f:
            return json.load(f)
    return []

@app.post("/api/tour")
async def save_tour(request: Request):
    """Saves the sequencer grid to the show file."""
    data = await request.json()
    with open(TOUR_FILE, "w") as f:
        json.dump(data, f, indent=4)
    return {"status": "success"}

@app.post("/api/ptz/move")
async def ptz_move(request: Request):
    """Proxies joystick movement commands to the worker."""
    data = await request.json()
    try:
        requests.post(f"{WORKER_1_URL}/api/ptz/move", json=data, timeout=1.0)
    except:
        pass
    return {"status": "success"}

@app.post("/api/ptz/save_preset")
async def ptz_preset(request: Request):
    """Proxies the hardware memory save command to the worker."""
    data = await request.json()
    try:
        requests.post(f"{WORKER_1_URL}/api/ptz/save_preset", json=data, timeout=1.0)
    except:
        pass
    return {"status": "success"}

@app.post("/api/tour/toggle")
def toggle_tour():
    """Future hook: Will start/stop the director.py state machine."""
    print("[HUB] Tour toggle requested.")
    return {"status": "acknowledged"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)