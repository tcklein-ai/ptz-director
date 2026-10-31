import obsws_python as obs

class OBSManager:
    def __init__(self, host='localhost', port=4455, password='', on_scene_change=None):
        """Initializes the connection to the OBS WebSocket server."""
        self.host = host
        self.port = port
        self.password = password
        self.on_scene_change = on_scene_change
        self.req = None
        self.event = None
        self.connected = False
        self.connect()

    def connect(self):
        self.disconnect() # Clean up any existing connection first
        try:
            self.req = obs.ReqClient(host=self.host, port=self.port, password=self.password, timeout=3)
            self.event = obs.EventClient(host=self.host, port=self.port, password=self.password)
            self.event.callback.register([self.on_current_program_scene_changed])
            self.connected = True
            print(f"Successfully connected to OBS WebSocket at {self.host}:{self.port}")
            return True
        except Exception as e:
            self.connected = False
            print(f"Failed to connect to OBS at {self.host}:{self.port}. Error: {e}")
            return False

    def reconnect(self, host, port, password):
        """Allows the web UI to inject new connection settings dynamically."""
        self.host = host
        self.port = port
        self.password = password
        return self.connect()

    def on_current_program_scene_changed(self, data):
        scene_name = data.scene_name
        if self.on_scene_change:
            self.on_scene_change(scene_name)

    def set_scene(self, scene_name: str):
        if self.req:
            try:
                self.req.set_current_program_scene(scene_name)
            except Exception as e:
                print(f"Failed to change scene '{scene_name}'. Error: {e}")

    def disconnect(self):
        if self.event:
            try:
                self.event.disconnect()
            except:
                pass
        self.connected = False