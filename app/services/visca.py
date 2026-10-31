import socket

class PTZCamera:
    """Handles UDP VISCA motor and memory commands."""
    
    def __init__(self, ip, port=1259):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Timeout prevents the worker thread from freezing if the camera drops off the network
        self.sock.settimeout(0.1) 

    def send_visca_command(self, payload):
        """Helper function to send raw hex bytes over UDP."""
        try:
            self.sock.sendto(bytes.fromhex(payload), (self.ip, self.port))
        except Exception as e:
            # Silently fail so we don't spam the console if the camera is temporarily offline
            pass

    def move(self, pan_speed, tilt_speed, direction):
        """Commands the physical motors."""
        p = hex(pan_speed)[2:].zfill(2)
        t = hex(tilt_speed)[2:].zfill(2)
        
        # Sony VISCA Pan/Tilt payload structure:
        # 81 01 06 01 [PanSpeed] [TiltSpeed] [PanDir] [TiltDir] FF
        commands = {
            "up":        f"81 01 06 01 {p} {t} 03 01 FF",
            "down":      f"81 01 06 01 {p} {t} 03 02 FF",
            "left":      f"81 01 06 01 {p} {t} 01 03 FF",
            "right":     f"81 01 06 01 {p} {t} 02 03 FF",
            "up_left":   f"81 01 06 01 {p} {t} 01 01 FF",
            "up_right":  f"81 01 06 01 {p} {t} 02 01 FF",
            "down_left": f"81 01 06 01 {p} {t} 01 02 FF",
            "down_right":f"81 01 06 01 {p} {t} 02 02 FF",
            "stop":      f"81 01 06 01 {p} {t} 03 03 FF"
        }
        
        cmd = commands.get(direction)
        if cmd:
            self.send_visca_command(cmd)

    def save_preset(self, preset_number: int):
        """Saves current X/Y/Z position to the camera's internal memory bank."""
        # Standard VISCA limits presets to 0-255. 
        # Most web UIs start at 1, so we often subtract 1, but we'll send it raw here.
        if 0 <= preset_number <= 255:
            p_hex = hex(preset_number)[2:].zfill(2)
            # Memory Set Command
            cmd = f"81 01 04 3F 01 {p_hex} FF"
            self.send_visca_command(cmd)
            print(f"[VISCA] Saved Preset {preset_number} to camera memory.")
        else:
            print("[VISCA] Error: Preset number out of range (0-255).")

    def recall_preset(self, preset_number: int):
        """Drives the camera to a previously saved memory bank position."""
        if 0 <= preset_number <= 255:
            p_hex = hex(preset_number)[2:].zfill(2)
            # Memory Recall Command
            cmd = f"81 01 04 3F 02 {p_hex} FF"
            self.send_visca_command(cmd)
            print(f"[VISCA] Recalling Preset {preset_number} from camera memory.")
        else:
            print("[VISCA] Error: Preset number out of range (0-255).")