import uvicorn
import json
import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.services.obs_link import OBSManager
from app.services.director import SceneDirector

CONFIG_FILE = "config.json"
TOUR_FILE = "tour_config.json"
WORKER_1_URL = "http://127.0.0.1:8001"

global_state = {
    "current_scene": "Unknown",
    "obs_host": "localhost",
    "obs_port": 4455,
    "obs_password": "",
    "obs_connected": False,
    "cam_source": "0", 
    "cam_ip": "192.168.1.100",
    "cam_port": 1259,
    "p": 0.05, "i": 0.00, "d": 0.02, "deadband": 40, "loop_delay": 50,
    "tracking_active": False,
    "error_x": 0,
    "error_y": 0,
    "last_command": "System Starting..."
}

obs_manager = None
director = None 
templates = Jinja2Templates(directory="app/templates")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                keys = ["p", "i", "d", "deadband", "loop_delay", "obs_host", "obs_port", "obs_password", "cam_ip", "cam_port", "cam_source"]
                for k in keys:
                    if k in saved: global_state[k] = saved[k]
        except Exception as e: 
            print(f"Error loading config: {e}")

def save_config():
    keys = ["p", "i", "d", "deadband", "loop_delay", "obs_host", "obs_port", "obs_password", "cam_ip", "cam_port", "cam_source"]
    data = {k: global_state[k] for k in keys}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

def push_config_to_worker():
    keys = ["p", "i", "d", "deadband", "loop_delay", "cam_ip", "cam_port", "cam_source"]
    payload = {k: global_state[k] for k in keys}
    try:
        requests.post(f"{WORKER_1_URL}/api/config", json=payload, timeout=1.0)
    except requests.exceptions.RequestException:
        pass

def handle_scene_change(scene_name: str):
    global_state["current_scene"] = scene_name

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    
    global obs_manager, director
    obs_manager = OBSManager(
        host=global_state["obs_host"], port=global_state["obs_port"], 
        password=global_state["obs_password"], on_scene_change=handle_scene_change
    )
    global_state["obs_connected"] = obs_manager.connected
    
    director = SceneDirector(config_path=TOUR_FILE, obs_manager=obs_manager, workers_map={"cam_1": WORKER_1_URL})
    push_config_to_worker()
    yield
    if obs_manager: obs_manager.disconnect()
    if director: director.stop_tour()

app = FastAPI(title="PTZ Director Hub", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

@app.get("/api/toggle")
def toggle_tracking():
    try:
        response = requests.post(f"{WORKER_1_URL}/api/toggle", timeout=1.0)
        global_state["tracking_active"] = response.json().get("active", False)
    except: pass
    return {"active": global_state["tracking_active"]}

@app.get("/api/state")
def get_state():
    try:
        res = requests.get(f"{WORKER_1_URL}/api/state", timeout=0.2).json()
        global_state["error_x"] = res.get("error_x", 0)
        global_state["error_y"] = res.get("error_y", 0)
        global_state["tracking_active"] = res.get("tracking_active", False)
        global_state["last_command"] = res.get("last_command", "Idle")
    except:
        global_state["error_x"] = 0
        global_state["error_y"] = 0
        global_state["last_command"] = "Worker Offline"
        
    if director and director.is_running and director.cues:
        current_cue = director.cues[director.current_cue_idx]
        global_state["tour_live_scene"] = current_cue.get("obs_scene", "--")
        next_idx = (director.current_cue_idx + 1) % len(director.cues)
        global_state["tour_next_scene"] = director.cues[next_idx].get("obs_scene", "--")
        global_state["tour_active"] = True
    else:
        global_state["tour_live_scene"] = "--"
        global_state["tour_next_scene"] = "--"
        global_state["tour_active"] = False
        
    return global_state

@app.post("/api/hub_config")
async def update_hub_config(request: Request):
    global obs_manager
    data = await request.json()
    
    reconnect_obs = False
    for k in ["obs_host", "obs_port", "obs_password"]: 
        if k in data and data[k] != global_state[k]: 
            global_state[k] = data[k]
            reconnect_obs = True
    
    global_state["obs_port"] = int(global_state["obs_port"])
    if reconnect_obs and obs_manager:
        global_state["obs_connected"] = obs_manager.reconnect(global_state["obs_host"], global_state["obs_port"], global_state["obs_password"])

    for k in ["p", "i", "d", "deadband", "loop_delay", "cam_ip", "cam_port", "cam_source"]:
        if k in data:
            if k in ["p", "i", "d"]: global_state[k] = float(data[k])
            elif k in ["deadband", "loop_delay", "cam_port"]: global_state[k] = int(data[k])
            else: global_state[k] = str(data[k])
            
    save_config()
    push_config_to_worker()
    return {"status": "success"}

@app.get("/api/video_feed")
def video_feed():
    def generate():
        try:
            with requests.get(f"{WORKER_1_URL}/api/video_feed", stream=True, timeout=5.0) as r:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: yield chunk
        except requests.exceptions.RequestException: pass
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/tour")
def get_tour():
    if os.path.exists(TOUR_FILE):
        with open(TOUR_FILE, "r") as f: return json.load(f)
    return []

@app.post("/api/tour")
async def save_tour(request: Request):
    data = await request.json()
    with open(TOUR_FILE, "w") as f: json.dump(data, f, indent=4)
    if director: director.load_config()
    return {"status": "success"}

@app.post("/api/ptz/move")
async def ptz_move(request: Request):
    data = await request.json()
    try: requests.post(f"{WORKER_1_URL}/api/ptz/move", json=data, timeout=1.0)
    except: pass
    return {"status": "success"}

@app.post("/api/ptz/save_preset")
async def ptz_preset(request: Request):
    data = await request.json()
    try: requests.post(f"{WORKER_1_URL}/api/ptz/save_preset", json=data, timeout=1.0)
    except: pass
    return {"status": "success"}

@app.post("/api/tour/toggle")
def toggle_tour():
    if director:
        if director.is_running: director.stop_tour()
        else: director.start_tour()
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)