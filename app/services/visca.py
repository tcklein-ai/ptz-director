import socket

class PTZCamera:
    def __init__(self, ip, port=1259):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1) 

    def send_visca_command(self, payload):
        try:
            self.sock.sendto(bytes.fromhex(payload), (self.ip, self.port))
        except Exception:
            pass

    def move(self, pan_speed, tilt_speed, direction):
        p = hex(pan_speed)[2:].zfill(2)
        t = hex(tilt_speed)[2:].zfill(2)
        
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

    def zoom(self, speed, direction):
        """Commands variable speed optical zoom (speed 0-7)."""
        z = hex(min(7, max(0, speed)))[2:]
        if direction == "in":
            cmd = f"81 01 04 07 2{z} FF"
        elif direction == "out":
            cmd = f"81 01 04 07 3{z} FF"
        else:
            cmd = "81 01 04 07 00 FF"
        self.send_visca_command(cmd)

    def save_preset(self, preset_number: int):
        if 0 <= preset_number <= 255:
            p_hex = hex(preset_number)[2:].zfill(2)
            self.send_visca_command(f"81 01 04 3F 01 {p_hex} FF")

    def recall_preset(self, preset_number: int):
        if 0 <= preset_number <= 255:
            p_hex = hex(preset_number)[2:].zfill(2)
            self.send_visca_command(f"81 01 04 3F 02 {p_hex} FF")