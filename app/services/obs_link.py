import obsws_python as obs

class OBSManager:
    def __init__(self, host='localhost', port=4455, password='', on_scene_change=None):
        self.host = host
        self.port = port
        self.password = password
        self.on_scene_change = on_scene_change
        self.client = None
        self.event_client = None
        self.connected = False
        self.connect()

    def connect(self):
        try:
            self.client = obs.ReqClient(host=self.host, port=self.port, password=self.password, timeout=3)
            self.event_client = obs.EventClient(host=self.host, port=self.port, password=self.password, timeout=3)
            self.event_client.callback.register(self.on_event)
            self.connected = True
            print(f"Successfully connected to OBS WebSocket at {self.host}:{self.port}")
        except Exception as e:
            self.connected = False
            print(f"Failed to connect to OBS: {e}")

    def disconnect(self):
        if self.event_client:
            try: self.event_client.disconnect()
            except: pass
        self.connected = False

    def reconnect(self, host, port, password):
        self.disconnect()
        self.host = host
        self.port = port
        self.password = password
        self.connect()
        return self.connected

    def on_event(self, data):
        if data.name == "CurrentProgramSceneChanged":
            if self.on_scene_change:
                scene_name = getattr(data, 'scene_name', 'Unknown')
                self.on_scene_change(scene_name)

    def set_scene(self, scene_name):
        if self.connected and self.client:
            try:
                self.client.set_current_program_scene(scene_name)
            except Exception as e:
                print(f"Error setting OBS scene: {e}")

    def get_scenes(self):
        """NEW: Fetches the list of all available scenes from OBS."""
        if self.connected and self.client:
            try:
                resp = self.client.get_scene_list()
                scenes = []
                for s in getattr(resp, 'scenes', []):
                    if isinstance(s, dict):
                        scenes.append(s.get('sceneName', s.get('scene_name', '')))
                    else:
                        scenes.append(getattr(s, 'sceneName', getattr(s, 'scene_name', '')))
                return [s for s in scenes if s]
            except Exception as e:
                print(f"Error fetching OBS scenes: {e}")
        return []