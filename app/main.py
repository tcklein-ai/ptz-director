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

WORKERS = {
    "cam_1": "http://127.0.0.1:8001",
    "cam_2": "http://127.0.0.1:8002"
}

global_state = {
    "current_scene": "Unknown",
    "obs_host": "localhost", "obs_port": 4455, "obs_password": "", "obs_connected": False,
    
    "cam1_source": "0", "cam1_ip": "192.168.1.100", "cam1_port": 5678, "cam1_obs_scene": "Cam 1 Wide", 
    "cam1_p": 0.005, "cam1_p_max": 0.030, "cam1_i": 0.000, "cam1_d": 0.010, "cam1_deadband": 60, "cam1_loop_delay": 33,
    "cam1_presets": {"1": "Preset 1", "2": "Preset 2"},
    "cam1_error_x": 0, "cam1_error_y": 0, "cam1_tracking_active": False, "cam1_last_command": "Offline",

    "cam2_source": "1", "cam2_ip": "192.168.1.101", "cam2_port": 5678, "cam2_obs_scene": "Cam 2 Wide", 
    "cam2_p": 0.005, "cam2_p_max": 0.030, "cam2_i": 0.000, "cam2_d": 0.010, "cam2_deadband": 60, "cam2_loop_delay": 33,
    "cam2_presets": {"1": "Preset 1", "2": "Preset 2"},
    "cam2_error_x": 0, "cam2_error_y": 0, "cam2_tracking_active": False, "cam2_last_command": "Offline",
}

obs_manager = None
director = None 
templates = Jinja2Templates(directory="app/templates")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                for k in saved:
                    if k == "cam_1_obs_scene":
                        global_state["cam1_obs_scene"] = saved[k]
                    elif k == "cam_2_obs_scene":
                        global_state["cam2_obs_scene"] = saved[k]
                    elif k in global_state: 
                        global_state[k] = saved[k]
        except Exception: pass

def save_config():
    keys = ["obs_host", "obs_port", "obs_password",
            "cam1_source", "cam1_ip", "cam1_port", "cam1_obs_scene", "cam1_p", "cam1_p_max", "cam1_i", "cam1_d", "cam1_deadband", "cam1_presets",
            "cam2_source", "cam2_ip", "cam2_port", "cam2_obs_scene", "cam2_p", "cam2_p_max", "cam2_i", "cam2_d", "cam2_deadband", "cam2_presets"]
    data = {k: global_state[k] for k in keys}
    with open(CONFIG_FILE, "w") as f: json.dump(data, f, indent=4)

def push_config_to_workers():
    c1_payload = {
        "cam_ip": global_state["cam1_ip"], "cam_port": global_state["cam1_port"], "cam_source": global_state["cam1_source"],
        "p": global_state["cam1_p"], "p_max": global_state["cam1_p_max"], "i": global_state["cam1_i"], "d": global_state["cam1_d"], "deadband": global_state["cam1_deadband"]
    }
    try: requests.post(f"{WORKERS['cam_1']}/api/config", json=c1_payload, timeout=2.0)
    except: pass

    c2_payload = {
        "cam_ip": global_state["cam2_ip"], "cam_port": global_state["cam2_port"], "cam_source": global_state["cam2_source"],
        "p": global_state["cam2_p"], "p_max": global_state["cam2_p_max"], "i": global_state["cam2_i"], "d": global_state["cam2_d"], "deadband": global_state["cam2_deadband"]
    }
    try: requests.post(f"{WORKERS['cam_2']}/api/config", json=c2_payload, timeout=2.0)
    except: pass

def get_cam_scene(cam_id):
    prefix = cam_id.replace('_', '')
    scene = global_state.get(f"{prefix}_obs_scene", "Unknown")
    return scene if scene and scene.strip() else "Unknown"

def get_action_label(cam_id, action):
    if action == "track_face": return "Auto-Track"
    if action.startswith("preset_"):
        pid = action.split("_")[1]
        presets = global_state.get(f"{cam_id.replace('_', '')}_presets", {})
        return presets.get(pid, f"Preset {pid}")
    return action

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    global obs_manager, director
    obs_manager = OBSManager(host=global_state["obs_host"], port=global_state["obs_port"], password=global_state["obs_password"], on_scene_change=lambda s: global_state.update({"current_scene": s}))
    global_state["obs_connected"] = obs_manager.connected
    
    director = SceneDirector(
        config_path=TOUR_FILE, 
        obs_manager=obs_manager, 
        workers_map=WORKERS, 
        scene_lookup_cb=get_cam_scene,
        current_scene_cb=lambda: global_state.get("current_scene", "Unknown")
    )
    
    push_config_to_workers()
    yield
    if obs_manager: obs_manager.disconnect()
    if director: director.stop_tour()

app = FastAPI(title="PTZ Director Hub", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request): return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

@app.get("/api/state")
def get_state():
    try:
        r1 = requests.get(f"{WORKERS['cam_1']}/api/state", timeout=0.2).json()
        global_state.update({"cam1_error_x": r1.get("error_x",0), "cam1_error_y": r1.get("error_y",0), "cam1_tracking_active": r1.get("tracking_active",False), "cam1_last_command": r1.get("last_command","Idle")})
    except: global_state.update({"cam1_last_command": "Worker 1 Offline"})
    
    try:
        r2 = requests.get(f"{WORKERS['cam_2']}/api/state", timeout=0.2).json()
        global_state.update({"cam2_error_x": r2.get("error_x",0), "cam2_error_y": r2.get("error_y",0), "cam2_tracking_active": r2.get("tracking_active",False), "cam2_last_command": r2.get("last_command","Idle")})
    except: global_state.update({"cam2_last_command": "Worker 2 Offline"})
        
    if director and director.is_running and director.cues:
        d_stat = director.get_status()
        current_idx = director.current_cue_idx
        current_cue = director.cues[current_idx]
        cam_id = current_cue.get("camera_id", "cam_1")
        
        obs_scene = get_cam_scene(cam_id)
        action_lbl = get_action_label(cam_id, current_cue.get("action", "preset_1"))
        cam_name = cam_id.replace('_', ' ').title()
        
        global_state["tour_live_scene"] = f"#{current_idx + 1} | {cam_name} | {action_lbl} (OBS: {obs_scene})"
        
        next_idx = (current_idx + 1) % len(director.cues)
        for _ in range(len(director.cues)):
            if director.cues[next_idx].get("enabled", True): break
            next_idx = (next_idx + 1) % len(director.cues)
            
        next_cue = director.cues[next_idx]
        next_cam = next_cue.get("camera_id", "cam_1")
        next_obs = get_cam_scene(next_cam)
        next_action_lbl = get_action_label(next_cam, next_cue.get("action", "preset_1"))
        next_cam_name = next_cam.replace('_', ' ').title()
        
        global_state["tour_next_scene"] = f"#{next_idx + 1} | {next_cam_name} | {next_action_lbl} (OBS: {next_obs})"
        global_state["tour_active"] = True
        global_state["tour_phase"] = d_stat["phase"]
        global_state["tour_time_total"] = d_stat["timer_duration"]
        global_state["tour_time_rem"] = round(d_stat["timer_duration"] - d_stat["timer_elapsed"], 1)
        global_state["tour_error"] = d_stat.get("error", "")
    else:
        global_state.update({"tour_live_scene": "--", "tour_next_scene": "--", "tour_active": False, "tour_phase": "IDLE", "tour_time_rem": 0.0, "tour_time_total": 1.0})
        if director: global_state["tour_error"] = director.get_status().get("error", "")
    
    return global_state

@app.post("/api/hub_config")
async def update_hub_config(request: Request):
    global obs_manager
    data = await request.json()
    reconnect = False
    for k in ["obs_host", "obs_port", "obs_password"]: 
        if k in data and data[k] != global_state[k]: 
            global_state[k] = data[k]
            reconnect = True
    if reconnect and obs_manager: global_state["obs_connected"] = obs_manager.reconnect(global_state["obs_host"], int(global_state["obs_port"]), global_state["obs_password"])

    keys = ["cam1_source", "cam1_ip", "cam1_port", "cam1_obs_scene", "cam1_p", "cam1_p_max", "cam1_i", "cam1_d", "cam1_deadband", "cam1_presets",
            "cam2_source", "cam2_ip", "cam2_port", "cam2_obs_scene", "cam2_p", "cam2_p_max", "cam2_i", "cam2_d", "cam2_deadband", "cam2_presets"]
    for k in keys:
        if k in data:
            if k.endswith("_presets"): global_state[k] = data[k]
            elif k.endswith("_p") or k.endswith("_p_max") or k.endswith("_i") or k.endswith("_d"): global_state[k] = float(data[k])
            elif k.endswith("_deadband") or k.endswith("_port"): global_state[k] = int(data[k])
            else: global_state[k] = str(data[k])
            
    save_config()
    push_config_to_workers()
    return {"status": "success"}

@app.get("/api/obs/scenes")
def get_obs_scenes():
    scenes = []
    if obs_manager and obs_manager.connected: scenes = obs_manager.get_scenes()
    return {"scenes": scenes}

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

@app.post("/api/tour/toggle")
def toggle_tour():
    if director:
        if director.is_running: director.stop_tour()
        else: director.start_tour()
    return {"status": "success"}

@app.post("/api/tour/go")
async def go_tour(request: Request):
    data = await request.json()
    if director: director.trigger_cue(int(data.get("index", 0)))
    return {"status": "success"}

def route_camera_command(endpoint: str, data: dict):
    cam = data.get("camera_id", "cam_1")
    url = WORKERS.get(cam)
    if url:
        try: requests.post(f"{url}{endpoint}", json=data, timeout=1.0)
        except: pass

@app.post("/api/toggle")
async def toggle_tracking(request: Request):
    data = await request.json()
    route_camera_command("/api/toggle", data)
    return {"status": "success"}

@app.post("/api/target/set")
async def set_target(request: Request):
    route_camera_command("/api/target/set", await request.json())
    return {"status": "success"}

@app.post("/api/target/clear")
async def clear_target(request: Request):
    route_camera_command("/api/target/clear", await request.json())
    return {"status": "success"}

@app.post("/api/ptz/move")
async def ptz_move(request: Request):
    route_camera_command("/api/ptz/move", await request.json())
    return {"status": "success"}

@app.post("/api/ptz/zoom")
async def ptz_zoom(request: Request):
    route_camera_command("/api/ptz/zoom", await request.json())
    return {"status": "success"}

@app.post("/api/ptz/save_preset")
async def ptz_preset(request: Request):
    route_camera_command("/api/ptz/save_preset", await request.json())
    return {"status": "success"}

@app.post("/api/ptz/recall_preset")
async def ptz_recall_preset(request: Request):
    route_camera_command("/api/ptz/recall_preset", await request.json())
    return {"status": "success"}

@app.get("/api/video_feed/{cam_id}")
def video_feed(cam_id: str):
    url = WORKERS.get(cam_id, WORKERS["cam_1"])
    def generate():
        try:
            with requests.get(f"{url}/api/video_feed", stream=True, timeout=5.0) as r:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: yield chunk
        except: pass
    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="warning")