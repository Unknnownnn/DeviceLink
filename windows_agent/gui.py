import sys
import queue
import logging
import socket
import time

for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

log_queue = queue.Queue()

class StdoutRedirector:
    def __init__(self, q):
        self.q = q

    def write(self, string):
        if string:
            self.q.put(string)

    def flush(self):
        pass

original_stdout = sys.stdout
original_stderr = sys.stderr
sys.stdout = StdoutRedirector(log_queue)
sys.stderr = StdoutRedirector(log_queue)

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DEVICELINK_DIR
log_file_path = os.path.join(DEVICELINK_DIR, "agent.log")

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")

fh = logging.FileHandler(log_file_path, encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logging.root.addHandler(fh)

sh = logging.StreamHandler(sys.stderr)
sh.setLevel(logging.INFO)
sh.setFormatter(formatter)
logging.root.addHandler(sh)

logging.root.setLevel(logging.INFO)

import threading
import asyncio
import customtkinter as ctk
import math
import random
import pystray
from PIL import Image, ImageDraw
import os
import re
import json
import urllib.request
import subprocess
import shutil
import tempfile

if getattr(sys, 'frozen', False):
    import time
    update_exe = os.path.join(os.path.dirname(sys.executable), "devlinkupdate.exe")
    if os.path.exists(update_exe):
        for _ in range(10):
            try:
                os.remove(update_exe)
                break
            except Exception:
                time.sleep(1)

VERSION = "1.5.1"
GITHUB_REPO = "Unknnownnn/DeviceLink"

def is_newer_version(current: str, latest: str) -> bool:
    def parse_ver(v):
        parts = []
        for x in v.strip().lower().lstrip('v').split('.'):
            m = re.match(r'^(\d+)', x)
            if m:
                parts.append(int(m.group(1)))
            else:
                parts.append(0)
        return parts

    curr_parts = parse_ver(current)
    lat_parts = parse_ver(latest)
    max_len = max(len(curr_parts), len(lat_parts))
    curr_parts += [0] * (max_len - len(curr_parts))
    lat_parts += [0] * (max_len - len(lat_parts))
    return lat_parts > curr_parts


sys.path.insert(0, os.path.dirname(__file__))

from nexuslink.settings_manager import SettingsManager
from main import run as run_backend

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def create_tray_image():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    custom_icon = os.path.join(base_path, "icon.png")
    if os.path.exists(custom_icon):
        try:
            img = Image.open(custom_icon).convert("RGBA")
            
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            w, h = img.size
            max_dim = max(w, h)
            margin = int(max_dim * 0.05) 
            new_size = max_dim + 2 * margin
            
            square_img = Image.new("RGBA", (new_size, new_size), (0, 0, 0, 0))
            square_img.paste(img, ((new_size - w) // 2, (new_size - h) // 2))
            img = square_img
            resample_filter = getattr(Image, 'Resampling', None)
            if resample_filter:
                resample = resample_filter.LANCZOS
            else:
                resample = Image.ANTIALIAS
            return img.resize((64, 64), resample)
        except Exception:
            pass

    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse((2, 2, 62, 62), fill=(255, 255, 255))
    return image


def set_file_progress(filename, bytes_sent, total_bytes):
    app = getattr(DeviceLinkApp, "_instance", None)
    if app:
        app.after(0, lambda: app.show_file_progress(filename, bytes_sent, total_bytes))


class SignalPulseLoader(ctk.CTkCanvas):
    def __init__(self, master, width=280, height=280, max_radius=110, **kwargs):
        # Resolve background color dynamically to blend in
        bg_color = kwargs.pop("bg", None)
        if bg_color is None:
            bg_color = self._get_parent_bg(master)
        
        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            **kwargs
        )
        
        self.width_val = width
        self.height_val = height
        self.max_radius = max_radius
        self.pulse_duration = 3.0
        self.ring_color = "#00E5FF"
        
        self.start_time = time.time()
        self.pulse_offsets = [0, 1.0, 2.0]
        self.running = False
        self._after_id = None

    def _get_parent_bg(self, master):
        try:
            color = master.cget("fg_color")
            if isinstance(color, (list, tuple)):
                mode = ctk.get_appearance_mode().lower()
                color = color[1] if mode == "dark" else color[0]
            if color == "transparent" or not color:
                return self._get_parent_bg(master.master)
            return color
        except Exception:
            return "#1E293B"

    def is_foreground(self):
        try:
            toplevel = self.winfo_toplevel()
            if hasattr(toplevel, "is_in_foreground"):
                return toplevel.is_in_foreground()
            return toplevel.winfo_viewable() and toplevel.state() == "normal"
        except Exception:
            return False

    def start(self):
        if not self.running:
            self.running = True
            self.start_time = time.time()
            self.animate()

    def stop(self):
        self.running = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def animate(self):
        if not self.running:
            return

        if not self.is_foreground():
            # Idle check when backgrounded/minimized
            self._after_id = self.after(500, self.animate)
            return

        self.delete("all")

        cx = self.width_val / 2
        cy = self.height_val / 2

        now = time.time()

        # Draw pulse rings
        for offset in self.pulse_offsets:
            age = ((now - self.start_time) - offset) % self.pulse_duration
            progress = age / self.pulse_duration
            radius = progress * self.max_radius
            opacity = max(0.0, 1.0 - progress)
            color = self.fade_color(self.ring_color, opacity)

            self.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=color,
                width=3
            )

        # Outer glow
        glow_radius = 18
        self.create_oval(
            cx - glow_radius,
            cy - glow_radius,
            cx + glow_radius,
            cy + glow_radius,
            fill="#0088AA",
            outline=""
        )

        # Center node
        self.create_oval(
            cx - 8,
            cy - 8,
            cx + 8,
            cy + 8,
            fill=self.ring_color,
            outline=""
        )

        self._after_id = self.after(16, self.animate)

    def fade_color(self, hex_color, alpha):
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        bg_color = self.cget("bg") or "#0f1117"
        bg_color = bg_color.lstrip("#")
        try:
            bg_r = int(bg_color[0:2], 16)
            bg_g = int(bg_color[2:4], 16)
            bg_b = int(bg_color[4:6], 16)
        except Exception:
            bg_r, bg_g, bg_b = 15, 17, 23

        r = int(bg_r + (r - bg_r) * alpha)
        g = int(bg_g + (g - bg_g) * alpha)
        b = int(bg_b + (b - bg_b) * alpha)

        return f"#{r:02x}{g:02x}{b:02x}"


class ConnectedAnimation(ctk.CTkCanvas):
    def __init__(self, master, width=280, height=280, **kwargs):
        bg_color = kwargs.pop("bg", None)
        if bg_color is None:
            bg_color = self._get_parent_bg(master)

        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            **kwargs
        )

        self.width_val = width
        self.height_val = height
        self.start_color = (0, 229, 255)   # cyan
        self.end_color = (0, 255, 149)     # green
        
        self.start_time = time.time()
        self.running = False
        self._after_id = None

    def _get_parent_bg(self, master):
        try:
            color = master.cget("fg_color")
            if isinstance(color, (list, tuple)):
                mode = ctk.get_appearance_mode().lower()
                color = color[1] if mode == "dark" else color[0]
            if color == "transparent" or not color:
                return self._get_parent_bg(master.master)
            return color
        except Exception:
            return "#1E293B"

    def is_foreground(self):
        try:
            toplevel = self.winfo_toplevel()
            if hasattr(toplevel, "is_in_foreground"):
                return toplevel.is_in_foreground()
            return toplevel.winfo_viewable() and toplevel.state() == "normal"
        except Exception:
            return False

    def start(self):
        if not self.running:
            self.running = True
            self.start_time = time.time()
            self.animate()

    def stop(self):
        self.running = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def interpolate_color(self, progress):
        r = int(self.start_color[0] + (self.end_color[0] - self.start_color[0]) * progress)
        g = int(self.start_color[1] + (self.end_color[1] - self.start_color[1]) * progress)
        b = int(self.start_color[2] + (self.end_color[2] - self.start_color[2]) * progress)
        return f"#{r:02x}{g:02x}{b:02x}"

    def animate(self):
        if not self.running:
            return

        if not self.is_foreground():
            self.was_in_background = True
            self._after_id = self.after(500, self.animate)
            return

        # If we just returned to foreground, restart animation timing
        if getattr(self, "was_in_background", False):
            self.start_time = time.time()
            self.was_in_background = False

        t = (time.time() - self.start_time) * 2.0
        self.draw_frame(t)

        if t > 3.0:
            self.draw_frame(3.0)
            self._after_id = None
            return

        self._after_id = self.after(16, self.animate)

    def draw_frame(self, t):
        self.delete("all")

        cx = self.width_val / 2
        cy = self.height_val / 2 - 20

        # Stage 1: Collapse ring inward
        if t < 1.4:
            p = t / 1.4
            radius = 70 * (1.0 - p)
            color = "#00e5ff"
            self.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=color,
                width=5
            )

        # Stage 2: Orb changes color
        if t >= 0.8:
            p = min((t - 0.8) / 0.8, 1)
            color = self.interpolate_color(p)
            glow = 18
            self.create_oval(
                cx - glow,
                cy - glow,
                cx + glow,
                cy + glow,
                fill=color,
                outline=""
            )
            self.create_oval(
                cx - 8,
                cy - 8,
                cx + 8,
                cy + 8,
                fill="white",
                outline=""
            )

        # Stage 3: Success pulse
        if 1.4 <= t <= 2.4:
            pulse_progress = (t - 1.4)
            pulse_radius = 20 + pulse_progress * 80
            opacity = max(0.0, 1.0 - pulse_progress)
            intensity = int(255 * opacity)
            pulse_color = f"#00{intensity:02x}95"
            self.create_oval(
                cx - pulse_radius,
                cy - pulse_radius,
                cx + pulse_radius,
                cy + pulse_radius,
                outline=pulse_color,
                width=3
            )

        # Stage 4: Text fade in
        if t > 1.8:
            fade = min((t - 1.8) / 0.6, 1)
            gray = int(120 + 135 * fade)
            color = f"#{gray:02x}{gray:02x}{gray:02x}"
            self.create_text(
                cx,
                cy + 80,
                text="CONNECTED SUCCESSFULLY",
                fill=color,
                font=("Segoe UI", 12, "bold")
            )


class RelaySuccessAnimation(ctk.CTkCanvas):
    def __init__(self, master, width=280, height=280, **kwargs):
        bg_color = kwargs.pop("bg", None)
        if bg_color is None:
            bg_color = self._get_parent_bg(master)

        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            **kwargs
        )

        self.width_val = width
        self.height_val = height
        
        self.cyan_color = "#00e5ff"
        self.green_color = "#00ff95"
        self.white_color = "#ffffff"
        
        self.start_time = time.time()
        self.running = False
        self._after_id = None

    def _get_parent_bg(self, master):
        try:
            color = master.cget("fg_color")
            if isinstance(color, (list, tuple)):
                mode = ctk.get_appearance_mode().lower()
                color = color[1] if mode == "dark" else color[0]
            if color == "transparent" or not color:
                return self._get_parent_bg(master.master)
            return color
        except Exception:
            return "#1E293B"

    def is_foreground(self):
        try:
            toplevel = self.winfo_toplevel()
            if hasattr(toplevel, "is_in_foreground"):
                return toplevel.is_in_foreground()
            return toplevel.winfo_viewable() and toplevel.state() == "normal"
        except Exception:
            return False

    def start(self):
        if not self.running:
            self.running = True
            self.start_time = time.time()
            self.animate()

    def stop(self):
        self.running = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def draw_glow_circle(self, x, y, r, color):
        outer_color = self.fade_color(color, 0.25)
        self.create_oval(
            x - r * 1.8,
            y - r * 1.8,
            x + r * 1.8,
            y + r * 1.8,
            fill=outer_color,
            outline=""
        )

        self.create_oval(
            x - r,
            y - r,
            x + r,
            y + r,
            fill=color,
            outline=""
        )

    def fade_color(self, hex_color, alpha):
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        bg_color = self.cget("bg") or "#0f1117"
        bg_color = bg_color.lstrip("#")
        try:
            bg_r = int(bg_color[0:2], 16)
            bg_g = int(bg_color[2:4], 16)
            bg_b = int(bg_color[4:6], 16)
        except Exception:
            bg_r, bg_g, bg_b = 15, 17, 23

        r = int(bg_r + (r - bg_r) * alpha)
        g = int(bg_g + (g - bg_g) * alpha)
        b = int(bg_b + (b - bg_b) * alpha)

        return f"#{r:02x}{g:02x}{b:02x}"

    def animate(self):
        if not self.running:
            return

        if not self.is_foreground():
            self.was_in_background = True
            self._after_id = self.after(500, self.animate)
            return

        # If we just returned to foreground, restart animation timing
        if getattr(self, "was_in_background", False):
            self.start_time = time.time()
            self.was_in_background = False

        t = (time.time() - self.start_time) * 2.0
        self.draw_frame(t)

        # Stop rendering once static threshold (3.2s) is reached to save CPU
        if t > 3.2:
            self.draw_frame(3.2)
            self._after_id = None
            return

        self._after_id = self.after(16, self.animate)

    def draw_frame(self, t):
        self.delete("all")

        left_x = 40
        relay_x = self.width_val / 2
        right_x = self.width_val - 40
        y = self.height_val / 2 - 20

        # 1. Devices
        self.draw_glow_circle(left_x, y, 10, self.cyan_color)
        self.draw_glow_circle(right_x, y, 10, self.cyan_color)

        # 2. Relay Node
        relay_color = self.cyan_color
        if t > 2:
            relay_color = self.green_color

        relay_radius = 14

        if 1 <= t <= 1.8:
            pulse = (t - 1) * 20
            self.create_oval(
                relay_x - pulse,
                y - pulse,
                relay_x + pulse,
                y + pulse,
                outline=self.cyan_color,
                width=2
            )

        self.draw_glow_circle(relay_x, y, relay_radius, relay_color)

        # 3. Packet 1 -> relay
        if t <= 1:
            progress = t / 1
            x = left_x + (relay_x - left_x) * progress
            self.create_oval(
                x - 6,
                y - 6,
                x + 6,
                y + 6,
                fill=self.white_color,
                outline=""
            )

        # 4. Packet relay -> device
        if 1.2 <= t <= 2.2:
            progress = (t - 1.2)
            x = relay_x + (right_x - relay_x) * progress
            self.create_oval(
                x - 6,
                y - 6,
                x + 6,
                y + 6,
                fill=self.white_color,
                outline=""
            )

        # 5. Route Activation
        if t > 2:
            self.create_line(
                left_x,
                y,
                relay_x,
                y,
                fill=self.green_color,
                width=4
            )
            self.create_line(
                relay_x,
                y,
                right_x,
                y,
                fill=self.green_color,
                width=4
            )

        # 6. Text
        if t > 2.4:
            fade = min((t - 2.4) / 0.8, 1)
            gray = int(100 + 155 * fade)
            color = f"#{gray:02x}{gray:02x}{gray:02x}"
            self.create_text(
                self.width_val / 2,
                y + 80,
                text="CONNECTED VIA SECURE RELAY",
                fill=color,
                font=("Segoe UI", 12, "bold")
            )


class AgentCanvas(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            bg="#0b0f14",
            highlightthickness=0,
            **kwargs
        )
        self.agent_state = "idle"  # idle, thinking, transition, streaming
        self.start_time = time.time()
        self.target_x = 60
        self.target_y = 60
        self.core_x = 450
        self.core_y = 200
        self.bind("<Configure>", self.on_resize)
        self.response_text = ""
        self.stream_index = 0
        self.response_box = None
        self.is_error = False

        # NeuralIdle wandering particles
        self.particles = []
        for _ in range(10):
            angle = random.uniform(0, math.pi * 2)
            distance = random.uniform(90, 200)
            x = 450 + math.cos(angle) * distance
            y = 200 + math.sin(angle) * distance
            self.particles.append({
                "x": x,
                "y": y,
                "vx": random.uniform(-0.25, 0.25),
                "vy": random.uniform(-0.25, 0.25),
                "size": random.uniform(1.5, 3)
            })

    def on_resize(self, event):
        self.width_val = event.width
        self.height_val = event.height
        if self.agent_state in ("idle", "thinking"):
            self.core_x = event.width / 2
            self.core_y = event.height / 2 - 35

    def set_state(self, state):
        self.agent_state = state
        self.start_time = time.time()

    def start_thinking(self):
        if self.response_box:
            self.response_box.place_forget()
        cx = getattr(self, "width_val", 900) / 2
        cy = getattr(self, "height_val", 400) / 2 - 35
        self.core_x = cx
        self.core_y = cy
        self.set_state("thinking")

    def show_response(self, text, is_error=False):
        self.response_text = text
        self.is_error = is_error
        self.set_state("transition")

    def begin_streaming(self):
        self.agent_state = "streaming"
        self.stream_index = 0
        if self.response_box:
            self.response_box.configure(state="normal")
            self.response_box.delete("1.0", "end")
            if self.is_error:
                self.response_box.configure(text_color="#ff5555")
            else:
                self.response_box.configure(text_color="#d7dde5")
            self.response_box.configure(state="disabled")
            self.response_box.place(relx=0.10, rely=0.22, relwidth=0.82, relheight=0.7)
            self.response_box.lift()
        self.stream_next()

    def stream_next(self):
        if self.agent_state != "streaming":
            return
        if self.stream_index >= len(self.response_text):
            return
        if self.response_box:
            self.response_box.configure(state="normal")
            self.response_box.insert("end", self.response_text[self.stream_index])
            self.response_box.see("end")
            self.response_box.configure(state="disabled")
        self.stream_index += 1
        self.after(12, self.stream_next)

    def draw_glow_orb(self, x, y, r):
        self.create_oval(
            x - r * 3, y - r * 3,
            x + r * 3, y + r * 3,
            fill="#08313a",
            outline=""
        )
        self.create_oval(
            x - r * 1.8, y - r * 1.8,
            x + r * 1.8, y + r * 1.8,
            fill="#0c5260",
            outline=""
        )
        self.create_oval(
            x - r, y - r,
            x + r, y + r,
            fill="#00e5ff",
            outline=""
        )

    def animate(self):
        try:
            self.delete("all")
        except Exception:
            return
        t = time.time() - self.start_time

        if self.agent_state == "idle":
            cx = getattr(self, "width_val", 900) / 2
            cy = getattr(self, "height_val", 400) / 2 - 35
            
            # Breathing core
            breathing = 8 + 0.8 * math.sin(t * 0.45)
            self.draw_glow_orb(cx, cy, breathing)
            
            # Drifting particles
            for particle in self.particles:
                dx = cx - particle["x"]
                dy = cy - particle["y"]
                distance = math.sqrt(dx * dx + dy * dy)
                
                if distance > 220:
                    particle["vx"] += dx * 0.0007
                    particle["vy"] += dy * 0.0007
                    
                particle["vx"] += random.uniform(-0.015, 0.015)
                particle["vy"] += random.uniform(-0.015, 0.015)
                particle["vx"] *= 0.995
                particle["vy"] *= 0.995
                particle["x"] += particle["vx"]
                particle["y"] += particle["vy"]
                
                r = particle["size"]
                # Soft glow
                self.create_oval(
                    particle["x"] - r * 2,
                    particle["y"] - r * 2,
                    particle["x"] + r * 2,
                    particle["y"] + r * 2,
                    fill="#103843",
                    outline=""
                )
                # Particle
                self.create_oval(
                    particle["x"] - r,
                    particle["y"] - r,
                    particle["x"] + r,
                    particle["y"] + r,
                    fill="#00e5ff",
                    outline=""
                )
                
            dots = int((t * 1.2) % 4)

            text = "Awaiting Input" + "." * dots

            for dx, dy in [
                (-1, -1), (-1, 0), (-1, 1),
                (0, -1),           (0, 1),
                (1, -1),  (1, 0),  (1, 1)
            ]:
                self.create_text(
                    cx + dx,
                    cy + 120 + dy,
                    text=text,
                    fill="#000000",
                    font=("Segoe UI", 14, "bold")
                )

            # Main text
            self.create_text(
                cx,
                cy + 120,
                text=text,
                fill="#aeb6c2",
                font=("Segoe UI", 14, "bold")
            )

        elif self.agent_state == "thinking":
            cx = getattr(self, "width_val", 900) / 2
            cy = getattr(self, "height_val", 400) / 2 - 35
            for radius, speed in [(70, 20), (110, -12), (150, 7)]:
                self.create_arc(
                    cx - radius, cy - radius,
                    cx + radius, cy + radius,
                    start=t * speed,
                    extent=290,
                    style="arc",
                    outline="#16303a"
                )
            particles = [
                (70, 0.9, "#00e5ff"),
                (110, -0.55, "#00ff95"),
                (150, 0.35, "#8a63ff")
            ]
            for radius, speed, color in particles:
                angle = t * speed * 2
                x = cx + radius * math.cos(angle)
                y = cy + radius * math.sin(angle)
                self.create_oval(
                    x - 2, y - 2,
                    x + 2, y + 2,
                    fill=color,
                    outline=""
                )
            breathing = 8 + 1.5 * math.sin(t * 0.9)
            self.draw_glow_orb(cx, cy, breathing)
            self.create_text(
                cx, cy + 180,
                text="Thinking...",
                fill="#bfc6d0",
                font=("Segoe UI", 16)
            )

        elif self.agent_state == "transition":
            dx = self.target_x - self.core_x
            dy = self.target_y - self.core_y
            self.core_x += dx * 0.08
            self.core_y += dy * 0.08
            self.draw_glow_orb(self.core_x, self.core_y, 8)
            if abs(dx) < 1 and abs(dy) < 1:
                self.begin_streaming()

        elif self.agent_state == "streaming":
            self.draw_glow_orb(self.target_x, self.target_y, 8)
            self.create_text(
                100, 60,
                anchor="w",
                text="",
                fill="white",
                font=("Segoe UI", 16, "bold")
            )

        self.after(16, self.animate)
def get_installed_start_apps():
    import subprocess
    import json
    try:
        # Merged PowerShell query using both Get-StartApps and Shell COM object for virtual AppsFolder.
        # This guarantees UWP Store apps like WhatsApp are found even if not indexed in the Start Menu.
        cmd_str = (
            "$apps = @(); "
            "try { $apps += Get-StartApps | Select-Object Name, @{Name='AppID';Expression={$_.AppID}} } catch {}; "
            "try { "
            "  $shell = New-Object -ComObject Shell.Application; "
            "  $folder = $shell.Namespace('shell:AppsFolder'); "
            "  $apps += $folder.Items() | Select-Object @{Name='Name';Expression={$_.Name}}, @{Name='AppID';Expression={$_.Path}} "
            "} catch {}; "
            "$apps | Group-Object AppID | Foreach { $_.Group[0] } | ConvertTo-Json -Compress"
        )
        cmd = ["powershell", "-NoProfile", "-Command", cmd_str]
        # 0x08000000 corresponds to CREATE_NO_WINDOW to prevent PowerShell console flashing
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=0x08000000)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                return [data]
            return data
    except Exception as e:
        import sys
        print(f"Error retrieving installed apps: {e}", file=sys.__stderr__)
    return []


def get_shortcut_icon(label: str, item_type: str) -> str:
    label_lower = label.lower()
    if "spotify" in label_lower or "music" in label_lower or "song" in label_lower:
        return "🎵"
    elif "youtube" in label_lower or "netflix" in label_lower or "video" in label_lower or "tv" in label_lower:
        return "📺"
    elif "discord" in label_lower or "chat" in label_lower or "messenger" in label_lower or "whatsapp" in label_lower or "telegram" in label_lower:
        return "💬"
    elif "calculator" in label_lower or "calc" in label_lower:
        return "🧮"
    elif "firefox" in label_lower or "chrome" in label_lower or "safari" in label_lower or "edge" in label_lower or "browser" in label_lower or "internet" in label_lower:
        return "🌐"
    elif "notepad" in label_lower or "write" in label_lower or "text" in label_lower or "editor" in label_lower:
        return "📝"
    elif "explorer" in label_lower or "files" in label_lower or "folder" in label_lower or "directory" in label_lower:
        return "📁"
    elif "settings" in label_lower or "control panel" in label_lower or "config" in label_lower:
        return "⚙"
    elif item_type.lower() == "steam":
        return "🎮"
    elif item_type.lower() == "url":
        return "🌐"
    else:
        return "💻"


class ShortcutCard(ctk.CTkFrame):
    def __init__(self, parent, icon, title, target, shortcut_type, on_edit, on_remove):
        super().__init__(
            parent,
            fg_color="#252a33",
            corner_radius=12,
            width=160,
            height=145
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        
        self.title = title
        self.target = target
        self.shortcut_type = shortcut_type
        self.default_icon = icon
        self.on_edit = on_edit
        self.on_remove = on_remove

        # Badge on the top-left
        self.badge = ctk.CTkLabel(
            self,
            text=shortcut_type.upper(),
            fg_color="#205c9c" if shortcut_type.lower() == "app" else ("#e67e22" if shortcut_type.lower() == "steam" else "#2ecc71"),
            corner_radius=6,
            width=50,
            height=18,
            font=("Segoe UI", 10, "bold")
        )
        self.badge.place(x=8, y=8)

        # Options Button (3 dots) on top-right
        self.menu_btn = ctk.CTkButton(
            self,
            text="⋮",
            fg_color="transparent",
            hover_color="#303743",
            width=24,
            height=24,
            font=("Segoe UI", 16, "bold"),
            text_color="white",
            corner_radius=12,
            command=self.show_options_menu
        )
        self.menu_btn.place(x=128, y=8)

        self.icon_label = ctk.CTkLabel(
            self,
            text=icon,
            font=("Segoe UI Emoji", 34)
        )
        self.icon_label.pack(pady=(38, 5))

        self.title_label = ctk.CTkLabel(
            self,
            text=self.truncate_text(title, 16),
            font=("Segoe UI", 13, "bold")
        )
        self.title_label.pack(pady=(2, 2))

        self.target_label = ctk.CTkLabel(
            self,
            text=self.truncate_text(target, 20),
            font=("Segoe UI", 10),
            text_color="#8a95a5"
        )
        self.target_label.pack(pady=(0, 5))

        # Bind hover effects
        for widget in [self, self.icon_label, self.title_label, self.target_label]:
            widget.bind("<Enter>", self.hover_on)
            widget.bind("<Leave>", self.hover_off)

        # Check in memory cache first to prevent flickering when tab re-maps
        app = self.winfo_toplevel()
        if hasattr(app, "icon_cache") and target in app.icon_cache:
            self.ctk_icon = app.icon_cache[target]
            self.icon_label.configure(image=self.ctk_icon, text="")
        else:
            # Launch async task to extract high-res icon
            threading.Thread(target=self._load_icon_async, daemon=True).start()

    def show_options_menu(self):
        import tkinter as tk
        
        # Create popup menu
        menu = tk.Menu(self, tearoff=0, bg="#1e2127", fg="white", activebackground="#3498db", activeforeground="white")
        menu.add_command(label="Edit", command=self.on_edit)
        menu.add_command(label="Remove", command=self.on_remove)
        
        # Display menu at button location
        try:
            x = self.menu_btn.winfo_rootx()
            y = self.menu_btn.winfo_rooty() + self.menu_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _load_icon_async(self):
        try:
            from nexuslink.server.ws_server import extract_shortcut_icon
            b64_str = extract_shortcut_icon(self.target, self.shortcut_type, size=64)
            if b64_str:
                app = self.winfo_toplevel()
                if hasattr(app, "ui_queue"):
                    app.ui_queue.put(lambda: self._update_icon(b64_str))
                else:
                    self.after(0, lambda: self._update_icon(b64_str))
        except Exception as e:
            import sys, traceback
            print(f"Error async loading icon for {self.title}: {e}", file=sys.__stderr__)
            traceback.print_exc(file=sys.__stderr__)

    def _update_icon(self, b64_str):
        try:
            import base64
            from io import BytesIO
            img_data = base64.b64decode(b64_str)
            img = Image.open(BytesIO(img_data))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            self.ctk_icon = ctk.CTkImage(light_image=img, dark_image=img, size=(48, 48))
            self.icon_label.configure(image=self.ctk_icon, text="")
            
            # Cache it in the main window context
            app = self.winfo_toplevel()
            if hasattr(app, "icon_cache"):
                app.icon_cache[self.target] = self.ctk_icon
        except Exception as e:
            import sys
            print(f"Error setting icon for {self.title}: {e}", file=sys.__stderr__)

    def hover_on(self, event):
        self.configure(fg_color="#303743")

    def hover_off(self, event):
        self.configure(fg_color="#252a33")

    def truncate_text(self, text, max_len=16):
        if len(text) <= max_len:
            return text
        return text[:max_len-3] + "..."


class AddCard(ctk.CTkFrame):
    def __init__(self, parent, command):
        super().__init__(
            parent,
            fg_color="transparent",
            border_width=2,
            border_color="#4d5563",
            corner_radius=12,
            width=160,
            height=145
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.command = command

        self.plus = ctk.CTkLabel(
            self,
            text="+",
            font=("Segoe UI", 38)
        )
        self.plus.pack(expand=True)

        for widget in [self, self.plus]:
            widget.bind("<Enter>", self.hover_on)
            widget.bind("<Leave>", self.hover_off)
            widget.bind("<Button-1>", self.on_click)

    def hover_on(self, event):
        self.configure(border_color="#3498db")

    def hover_off(self, event):
        self.configure(border_color="#4d5563")

    def on_click(self, event):
        if self.command:
            self.command()


class DeviceLinkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DeviceLink Dashboard")
        self.geometry("1050x650")
        self.resizable(False, False)
        self.settings = SettingsManager()
        self.shortcut_cards = {}
        self.add_card_widget = None
        self.icon_cache = {}
        self.ui_queue = queue.Queue()
        self.check_single_instance()

        if getattr(sys, 'frozen', False):
            old_exe = sys.executable + ".old"
            if os.path.exists(old_exe):
                try:
                    os.remove(old_exe)
                except Exception:
                    pass

        # Check for updates silently in a background thread
        threading.Thread(target=self.check_for_updates_silently, daemon=True).start()

        if "--minimized" in sys.argv:
            self.withdraw()

        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_path, "icon.ico")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        DeviceLinkApp._instance = self
        from nexuslink.server.handlers import register_app_instance
        register_app_instance(self)
        self.call_overlay_window = None
        self.last_status = None
        self.is_focused = True
        self.status_animation_task = None
        self.has_shown_udp_file_warning = False
        self.status_base_text = "Waiting for Android connection"
        self.bind("<FocusIn>", self.on_focus_in)
        self.bind("<FocusOut>", self.on_focus_out)
        self.bind("<Unmap>", lambda e: self.update_telemetry_sync_state() if e.widget == self else None)
        self.bind("<Map>", lambda e: self.update_telemetry_sync_state() if e.widget == self else None)

        self.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.log_history = []
        self.agent_chat_history = []
        self.logs_window = None
        self.log_textbox = None
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)
        self.tab_status = self.tabview.add("Status")
        self.tab_rules = self.tabview.add("Mobile Deck")
        self.tab_agent_test = self.tabview.add("AI Agent")
        self.tab_calls = self.tabview.add("Phone Calls")
        self.tab_android = self.tabview.add("Android")
        self.settings_btn = ctk.CTkButton(
            self, 
            text="⚙ Settings", 
            width=90, 
            height=28,
            fg_color="#1E293B",
            hover_color="#334155",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.open_settings_window
        )
        self.settings_btn.place(relx=0.98, rely=0.03, anchor="ne")

        self._build_status_tab()
        self._build_rules_tab()
        self._build_agent_test_tab()
        self._build_calls_tab()
        self.telemetry_sync_active = False
        self.messages_win = None
        self.desktop_deck_apps = []
        self.deck_app_widgets = []
        self.wallpaper_primary_color = ""
        self.wallpaper_secondary_color = ""
        self._build_android_tab()
        self.tabview.configure(command=self.on_tab_changed)
        self.check_logs_loop()
        self.check_ui_queue()
        self.backend_thread = threading.Thread(target=self.start_backend, daemon=True)
        self.backend_thread.start()
        self.setup_tray()
        self.update_connection_status_loop()
        self.trigger_status_animation()

    def _build_status_tab(self):
        status_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        status_frame.pack(fill="x", padx=10, pady=(15, 5))
        
        self.status_title = ctk.CTkLabel(
            status_frame, 
            text="DeviceLink Server", 
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.status_title.pack(anchor="w")

        self.status_info = ctk.CTkLabel(
            status_frame, 
            text="Open the Android app to connect.", 
            text_color="gray",
            font=ctk.CTkFont(size=12)
        )
        self.status_info.pack(anchor="w", pady=(2, 5))

        # Center area for animation and status
        self.center_status_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        self.center_status_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Pulse loader animation (starts stopped)
        self.pulse_loader = SignalPulseLoader(self.center_status_frame, width=280, height=280, max_radius=110)
        
        # Connected animation (starts stopped)
        self.connected_anim = ConnectedAnimation(self.center_status_frame, width=280, height=280)
        
        # Relay connected animation (starts stopped)
        self.relay_anim = RelaySuccessAnimation(self.center_status_frame, width=280, height=280)
        
        # Connection status container inside center_status_frame
        self.conn_status_frame = ctk.CTkFrame(self.center_status_frame, fg_color="#1E293B", height=36, corner_radius=8)
        
        self.status_dot = ctk.CTkLabel(
            self.conn_status_frame, 
            text="●", 
            text_color="#F59E0B", 
            font=ctk.CTkFont(size=14),
            height=36,
            width=24
        )
        self.status_dot.pack(side="left", padx=(12, 6))
        
        self.status_text = ctk.CTkLabel(
            self.conn_status_frame, 
            text="Waiting for Android connection", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#CBD5E1",
            height=36
        )
        self.status_text.pack(side="left", padx=(0, 12))

        button_row = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        button_row.pack(fill="x", side="bottom", padx=10, pady=(10, 20))

        self.show_qr_btn = ctk.CTkButton(
            button_row, 
            text="Show Pairing QR Code", 
            width=160, 
            command=self.show_qr_code
        )
        self.show_qr_btn.pack(side="left", padx=(0, 10))

        self.send_file_btn = ctk.CTkButton(
            button_row, 
            text="Send File to Device", 
            width=160, 
            command=self.send_file_to_device,
            state="disabled"
        )
        self.send_file_btn.pack(side="left", padx=(0, 10))

        self.show_logs_btn = ctk.CTkButton(
            button_row, 
            text="Show System Logs", 
            width=160, 
            command=self.show_logs_window
        )
        self.show_logs_btn.pack(side="left")

        self.progress_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")

        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="Sending file...",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.progress_label.pack(anchor="w", padx=10, pady=(15, 2))

        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            width=500,
            height=12,
            corner_radius=4
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=10, pady=(2, 5))


    def show_qr_code(self):
        from config import DEVICELINK_DIR
        qr_path = DEVICELINK_DIR / "pairing_qr.png"
        
        qr_window = ctk.CTkToplevel(self)
        qr_window.title("Pairing QR Code")
        qr_window.geometry("340x420")
        qr_window.resizable(False, False)
        qr_window.attributes("-topmost", True)
        if qr_path.exists():
            try:
                pil_img = Image.open(str(qr_path))
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(260, 260))
                
                img_label = ctk.CTkLabel(qr_window, image=ctk_img, text="")
                img_label.image = ctk_img 
                img_label.pack(pady=20)
                
                info_label = ctk.CTkLabel(
                    qr_window, 
                    text="Scan this QR code in the Android app to connect", 
                    font=ctk.CTkFont(size=12)
                )
                info_label.pack(pady=(0, 10))
            except Exception as e:
                err_label = ctk.CTkLabel(qr_window, text=f"Error loading QR image:\n{e}", text_color="red")
                err_label.pack(pady=40)
        else:
            err_label = ctk.CTkLabel(qr_window, text="QR Code not generated yet.\nMake sure the server is running.", text_color="yellow")
            err_label.pack(pady=40)

    def show_logs_window(self):
        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.lift()
            self.logs_window.focus()
            return
            
        # Create TopLevel window
        self.logs_window = ctk.CTkToplevel(self)
        self.logs_window.title("System Logs")
        self.logs_window.geometry("750x500")
        self.logs_window.resizable(False, False)
        
        # Ensure it stays on top
        self.logs_window.attributes("-topmost", True)
        
        # Console Logs Container
        ctk.CTkLabel(
            self.logs_window, 
            text="Console Output Logs", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))

        self.log_textbox = ctk.CTkTextbox(
            self.logs_window, 
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0A0915",
            text_color="#E1DDF5"
        )
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # Populate with existing log history
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", "".join(self.log_history))
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def send_file_to_device(self):
        from nexuslink.server.udp_server import get_active_udp_peer
        if get_active_udp_peer():
            if not getattr(self, "has_shown_udp_file_warning", False):
                from tkinter import messagebox
                messagebox.showwarning(
                    "Unreliable Connection Warning",
                    "You are currently connected via STUN UDP Hole Punching.\n\n"
                    "File transfers over UDP are unreliable. Packets may be dropped, "
                    "and large files may not be sent or received correctly."
                )
                self.has_shown_udp_file_warning = True

        filepath = ctk.filedialog.askopenfilename(
            title="Select File to Send to Device"
        )
        if filepath and os.path.exists(filepath):
            filename = os.path.basename(filepath)
            # Start background thread to send the file directly
            threading.Thread(target=self._send_file_worker, args=(filepath, filename), daemon=True).start()

    def _send_file_worker(self, filepath, filename):
        import base64
        import uuid
        import time
        from nexuslink.server.ws_server import send_message_to_all_peers_sync
        
        try:
            file_size = os.path.getsize(filepath)
            file_id = str(uuid.uuid4())
            
            print(f"[Console] Sending '{filename}' ({file_size} bytes) directly to phone...")
            
            # Update progress UI to start
            self.after(0, lambda: self.show_file_progress(filename, 0, file_size))
            
            # Send file_transfer_start
            send_message_to_all_peers_sync(
                "file_transfer_start", 
                {"file_id": file_id, "file_name": filename, "file_size": file_size}
            )
            
            CHUNK_SIZE = 64 * 1024  # 64 KB
            bytes_sent = 0
            seq = 0
            
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    b64_data = base64.b64encode(chunk).decode("utf-8")
                    send_message_to_all_peers_sync(
                        "file_chunk",
                        {"file_id": file_id, "sequence": seq, "data": b64_data}
                    )
                    
                    seq += 1
                    bytes_sent += len(chunk)
                    
                    # Update progress locally in sync with the paced sending
                    self._update_progress_from_thread(filename, bytes_sent, file_size)
                    
                    # Pace chunk sending to prevent packet drop/congestion over the network
                    time.sleep(0.015)
                    
            # Send file_transfer_complete
            send_message_to_all_peers_sync(
                "file_transfer_complete",
                {"file_id": file_id}
            )
            
            print(f"[Console] Successfully sent '{filename}' to phone.")
            self._update_progress_from_thread(filename, file_size, file_size)
            
        except Exception as e:
            print(f"[Console] Error sending file directly: {e}")
            self.after(0, lambda: self.progress_label.configure(text=f"Error sending '{filename}'"))
            self.after(3000, self.hide_file_progress)

    def _update_progress_from_thread(self, filename, bytes_sent, file_size):
        self.after(0, lambda: self.show_file_progress(filename, bytes_sent, file_size))

    def show_file_progress(self, filename, bytes_sent, total_bytes):
        try:
            if not self.progress_frame.winfo_viewable():
                self.progress_frame.pack(fill="x", padx=10, pady=(10, 0))
            
            pct = float(bytes_sent) / float(total_bytes) if total_bytes > 0 else 0.0
            pct_text = f"Sending '{filename}'... {int(pct * 100)}%"
            
            self.progress_label.configure(text=pct_text)
            self.progress_bar.set(pct)
            
            if bytes_sent >= total_bytes:
                self.progress_label.configure(text=f"Sent '{filename}' successfully!")
                self.progress_bar.set(1.0)
                # Hide the progress frame after 3 seconds
                self.after(3000, self.hide_file_progress)
        except Exception as e:
            print(f"[Console] Error updating file progress: {e}")

    def hide_file_progress(self):
        try:
            self.progress_frame.pack_forget()
            self.progress_bar.set(0.0)
        except Exception:
            pass

    def check_logs_loop(self):
        msgs = []
        try:
            while True:
                msg = log_queue.get_nowait()
                if msg:
                    msgs.append(msg)
        except queue.Empty:
            pass
            
        if msgs:
            self.append_logs_to_ui(msgs)
            
        is_visible = self.winfo_viewable()
        is_logs_open = self.logs_window and self.logs_window.winfo_exists()
        interval = 150 if (is_visible or is_logs_open) else 2000
        
        self.after(interval, self.check_logs_loop)

    def check_ui_queue(self):
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                if callback:
                    try:
                        callback()
                    except Exception as e:
                        import sys
                        print(f"Error in UI queue callback: {e}", file=sys.__stderr__)
        except queue.Empty:
            pass
        self.after(50, self.check_ui_queue)

    def refresh_connection_status(self, force=False):
        try:
            from nexuslink.server.ws_server import get_active_peers, get_cloud_relay_active
            from nexuslink.server.udp_server import get_active_udp_peer
            peers = get_active_peers()
            udp_peer = get_active_udp_peer()
            cloud_relay_active = get_cloud_relay_active()

            # Create a unique key representing the current connection state to check for changes
            peers_key = tuple(sorted(peers)) if peers else ()
            current_status = (peers_key, udp_peer, cloud_relay_active)

            if not force and self.last_status == current_status:
                return

            self.has_shown_udp_file_warning = False

            # Detect transition from disconnected/waiting to connected
            was_waiting = True
            if self.last_status:
                prev_peers, prev_udp, prev_cloud = self.last_status
                if prev_peers or prev_udp or prev_cloud:
                    was_waiting = False

            self.last_status = current_status
            self.animation_frame = 0  # Reset animation frame on state change

            if peers:
                peer_str = ", ".join(f"{p[0]}:{p[1]}" for p in peers)
                self.status_base_text = f"Connected via mDNS/LAN: {peer_str}"
                self.status_dot.configure(text="✔", text_color="#10B981") # Green
                self.status_text.configure(text=self.status_base_text, text_color="#10B981")
                self.set_phone_tab_state("normal")
                self.send_file_btn.configure(state="normal")
                
                # Update status tab layout for connected state
                self.pulse_loader.stop()
                self.pulse_loader.pack_forget()
                self.conn_status_frame.pack_forget()
                
                self.relay_anim.stop()
                self.relay_anim.pack_forget()
                
                self.connected_anim.pack_forget()
                self.connected_anim.pack(anchor="center", pady=(10, 10))
                self.connected_anim.start()
                self.status_info.configure(text=self.status_base_text, text_color="#10B981")
                
                if was_waiting:
                    self.run_checkmark_pulse(0)
            elif udp_peer:
                self.status_base_text = f"Connected via STUN UDP: {udp_peer[0]}:{udp_peer[1]}"
                self.status_dot.configure(text="✔", text_color="#3B82F6") # Blue
                self.status_text.configure(text=self.status_base_text, text_color="#3B82F6")
                self.set_phone_tab_state("normal")
                self.send_file_btn.configure(state="normal")
                
                # Update status tab layout for connected state
                self.pulse_loader.stop()
                self.pulse_loader.pack_forget()
                self.conn_status_frame.pack_forget()
                
                self.relay_anim.stop()
                self.relay_anim.pack_forget()
                
                self.connected_anim.pack_forget()
                self.connected_anim.pack(anchor="center", pady=(10, 10))
                self.connected_anim.start()
                self.status_info.configure(text=self.status_base_text, text_color="#3B82F6")
                
                if was_waiting:
                    self.run_checkmark_pulse(0)
            else:
                self.send_file_btn.configure(state="disabled")
                if cloud_relay_active:
                    self.status_base_text = "Connected via Cloud Relay"
                    self.status_dot.configure(text="✔", text_color="#06B6D4") # Cyan
                    self.status_text.configure(text=self.status_base_text, text_color="#06B6D4")
                    self.set_phone_tab_state("disabled")
                    
                    # Update status tab layout for connected state
                    self.pulse_loader.stop()
                    self.pulse_loader.pack_forget()
                    self.conn_status_frame.pack_forget()
                    
                    self.connected_anim.stop()
                    self.connected_anim.pack_forget()
                    
                    self.relay_anim.pack_forget()
                    self.relay_anim.pack(anchor="center", pady=(10, 10))
                    self.relay_anim.start()
                    self.status_info.configure(text=self.status_base_text, text_color="#06B6D4")
                    
                    if was_waiting:
                        self.run_checkmark_pulse(0)
                else:
                    self.status_base_text = "Waiting for Android connection"
                    self.status_dot.configure(text="●", text_color="#D97706", font=ctk.CTkFont(size=14)) # Reset dot and font size
                    self.status_text.configure(text=self.status_base_text, text_color="#D97706")
                    self.set_phone_tab_state("disabled")
                    
                    # Pack pulse loader and then status text below it for waiting state
                    self.connected_anim.stop()
                    self.connected_anim.pack_forget()
                    self.relay_anim.stop()
                    self.relay_anim.pack_forget()
                    
                    self.pulse_loader.pack_forget()
                    self.conn_status_frame.pack_forget()
                    self.pulse_loader.pack(anchor="center", pady=(10, 10))
                    self.pulse_loader.start()
                    self.conn_status_frame.pack(anchor="center", pady=(5, 10))
                    self.status_info.configure(text="Open the Android app to connect.", text_color="gray")
            
            # Keep telemetry sync state in sync with connection state
            self.update_telemetry_sync_state()
        except Exception as e:
            print(f"[Console] Error updating connection status: {e}")

    def update_connection_status_loop(self):
        self.refresh_connection_status()
        is_visible = self.winfo_viewable()
        interval = 3000 if is_visible else 10000
        self.after(interval, self.update_connection_status_loop)

    def handle_cloud_relay_disconnect(self):
        self.last_status = None
        self.refresh_connection_status(force=True)

    def set_phone_tab_state(self, state):
        try:
            if state == "disabled":
                if self.tabview.get() in ["Phone Calls", "Android"]:
                    self.tabview.set("Status")
                self.tabview._segmented_button._buttons_dict["Phone Calls"].configure(state="disabled")
                self.tabview._segmented_button._buttons_dict["Android"].configure(state="disabled")
            else:
                self.tabview._segmented_button._buttons_dict["Phone Calls"].configure(state="normal")
                self.tabview._segmented_button._buttons_dict["Android"].configure(state="normal")
        except Exception:
            pass

    def run_checkmark_pulse(self, frame_index):
        # 14 keyframes peaking at size 20 (fits within 32px container) at 25ms intervals for a total of 350ms
        pulse_frames = [8, 10, 12, 14, 16, 18, 19, 20, 19, 18, 16, 14, 13, 14]
        if frame_index < len(pulse_frames):
            size = pulse_frames[frame_index]
            try:
                self.status_dot.configure(font=ctk.CTkFont(size=size, weight="bold"))
            except Exception:
                pass
            # Schedule next frame in 25ms for a smooth 350ms animation
            self.after(25, lambda: self.run_checkmark_pulse(frame_index + 1))

    def on_focus_in(self, event=None):
        if event and event.widget != self:
            return
        self.is_focused = True
        self.trigger_status_animation()

    def on_focus_out(self, event=None):
        if event and event.widget != self:
            return
        self.is_focused = False

    def is_in_foreground(self):
        try:
            return self.winfo_exists() and self.winfo_viewable() and self.state() == "normal" and getattr(self, "is_focused", True)
        except Exception:
            return False

    def trigger_status_animation(self):
        if self.status_animation_task:
            try:
                self.after_cancel(self.status_animation_task)
            except Exception:
                pass
            self.status_animation_task = None
        self.run_status_animation()

    def run_status_animation(self):
        is_visible = self.winfo_viewable() and self.state() != "iconic"
        is_focused = getattr(self, "is_focused", True)

        if not is_visible or not is_focused:
            # Idle mode to check back less frequently and save CPU
            self.status_animation_task = self.after(1000, self.run_status_animation)
            return

        state_cat = "waiting"
        if self.last_status:
            peers_key, udp_peer, cloud_relay_active = self.last_status
            if peers_key:
                state_cat = "mdns"
            elif udp_peer:
                state_cat = "stun"
            elif cloud_relay_active:
                state_cat = "cloud"

        base_text = getattr(self, "status_base_text", "Waiting for Android connection")

        if state_cat == "waiting":
            try:
                self.status_text.configure(text=base_text)
            except Exception:
                pass
            self.status_animation_task = self.after(1000, self.run_status_animation)
        else:
            # Static text for connected states (no trailing cycling dots)
            try:
                self.status_text.configure(text=base_text)
            except Exception:
                pass
            # Slow check (1000ms) to monitor status changes with zero CPU usage
            self.status_animation_task = self.after(1000, self.run_status_animation)

    def append_logs_to_ui(self, msgs):
        cleaned_msgs = []
        for msg in msgs:
            # Skip terminal-only block-art QR characters and separator lines
            if "█" in msg or "▄" in msg or "▀" in msg or "===" in msg:
                continue
            if "DeviceLink" in msg and "Scan this QR code" in msg:
                continue
            if "Fingerprint:" in msg and "Host:" in msg:
                continue
                
            # Clean emojis and visual clutter
            replacements = {
                "✓": "[OK]",
                "✗": "[FAIL]",
                "←": "<-",
                "→": "->",
                "✔": "[OK]",
                "❌": "[FAIL]",
                "⚠️": "[WARN]",
                "ℹ️": "[INFO]"
            }
            for old, new in replacements.items():
                msg = msg.replace(old, new)
                
            # Filter all remaining non-ASCII characters to keep output clean and developer-first
            msg = re.sub(r'[^\x00-\x7F]+', '', msg)
            cleaned_msgs.append(msg)
            
        if not cleaned_msgs:
            return
            
        combined_msg = "".join(cleaned_msgs)
        self.log_history.append(combined_msg)
        # Cap history to avoid unbounded memory growth
        if len(self.log_history) > 2000:
            self.log_history = self.log_history[-1000:]
        
        # Forward to Android companion (excluding recursive pc_log events to avoid loops)
        forward_msgs = [m for m in cleaned_msgs if "pc_log" not in m]
        if forward_msgs:
            try:
                from nexuslink.server.ws_server import send_message_to_all_peers_sync
                send_message_to_all_peers_sync("pc_log", {"log": "".join(forward_msgs)})
            except Exception:
                pass
        
        # If the logs window is currently open, print to the UI textbox
        if self.logs_window and self.logs_window.winfo_exists() and self.log_textbox:
            try:
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", combined_msg)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
            except Exception:
                pass

    def _build_rules_tab(self):
        # Container frame for full-width layout
        self.rules_container = ctk.CTkFrame(self.tab_rules, fg_color="transparent")
        self.rules_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Configure single column (1 row, 1 column)
        self.rules_container.grid_columnconfigure(0, weight=1)
        self.rules_container.grid_rowconfigure(0, weight=1)

        # Shortcuts Menu (spanning full width)
        self.shortcuts_col_frame = ctk.CTkFrame(self.rules_container)
        self.shortcuts_col_frame.grid(row=0, column=0, sticky="nsew")

        # ── HEADER AND TOOLBAR (built once) ──────────────────────
        self.rules_header = ctk.CTkFrame(self.shortcuts_col_frame, fg_color="transparent")
        self.rules_header.pack(fill="x", padx=15, pady=(15, 10))

        title = ctk.CTkLabel(
            self.rules_header,
            text="Mobile Deck",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title.pack(side="left")

        # Toolbar
        self.rules_toolbar = ctk.CTkFrame(self.shortcuts_col_frame, fg_color="transparent")
        self.rules_toolbar.pack(fill="x", padx=15, pady=(0, 15))

        self.rules_search = ctk.CTkEntry(
            self.rules_toolbar,
            placeholder_text="Search shortcuts..."
        )
        self.rules_search.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 10)
        )
        self.rules_search.bind("<KeyRelease>", self.on_search_change)

        self.rules_add_btn = ctk.CTkButton(
            self.rules_toolbar,
            text="Add Shortcut",
            width=100,
            command=self.show_add_shortcut_window
        )
        self.rules_add_btn.pack(
            side="left"
        )

        self.rules_store_btn = ctk.CTkButton(
            self.rules_toolbar,
            text="Add Installed App",
            width=120,
            command=self.show_installed_apps_window
        )
        self.rules_store_btn.pack(
            side="left",
            padx=(10, 0)
        )

        # Scrollable grid frame for cards
        self.rules_scroll = ctk.CTkScrollableFrame(self.shortcuts_col_frame, fg_color="transparent")
        self.rules_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.refresh_rules_ui()

    def on_search_change(self, event):
        self.refresh_rules_ui()

    def show_add_shortcut_window(self):
        add_win = ctk.CTkToplevel(self)
        add_win.title("Add Shortcut")
        add_win.geometry("450x260")
        add_win.resizable(False, False)
        add_win.attributes("-topmost", True)

        ctk.CTkLabel(add_win, text="Add Mobile Deck Shortcut", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(15, 10))

        # Inputs container
        form_frame = ctk.CTkFrame(add_win, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(form_frame, text="Label:").grid(row=0, column=0, sticky="w", pady=2)
        label_entry = ctk.CTkEntry(form_frame, width=280, placeholder_text="e.g. Spotify")
        label_entry.grid(row=0, column=1, padx=10, pady=2)

        ctk.CTkLabel(form_frame, text="Target/Path:").grid(row=1, column=0, sticky="w", pady=2)
        path_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        path_frame.grid(row=1, column=1, padx=10, pady=2)

        target_entry = ctk.CTkEntry(path_frame, width=210, placeholder_text="Executable/Steam ID/URL")
        target_entry.pack(side="left", padx=(0, 5))
        
        browse_btn = ctk.CTkButton(path_frame, text="...", width=40, command=lambda: self.browse_exe(target_entry))
        browse_btn.pack(side="left")

        # Type row
        ctk.CTkLabel(form_frame, text="Type:").grid(row=2, column=0, sticky="w", pady=2)
        type_var = ctk.StringVar(value="app")
        
        def on_type_change_add(val):
            if val == "app":
                browse_btn.configure(state="normal")
            else:
                browse_btn.configure(state="disabled")

        type_menu = ctk.CTkOptionMenu(
            form_frame, values=["app", "steam", "url"], 
            variable=type_var, command=on_type_change_add, width=80
        )
        type_menu.grid(row=2, column=1, padx=10, pady=2, sticky="w")

        def save_new_shortcut():
            label = label_entry.get().strip()
            target = target_entry.get().strip()
            item_type = type_var.get()
            if label and target:
                shortcut_id = label.lower().replace(" ", "_")
                self.settings.add_shortcut(shortcut_id, label, item_type, target)
                self.refresh_rules_ui()
                add_win.destroy()
                from nexuslink.server.ws_server import sync_shortcuts_to_active_peers
                sync_shortcuts_to_active_peers()

        # Save / Cancel row
        btn_row = ctk.CTkFrame(add_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="gray", hover_color="#555555", command=add_win.destroy).pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="Add Shortcut", width=120, command=save_new_shortcut).pack(side="right", padx=5)

    def show_installed_apps_window(self):
        win = ctk.CTkToplevel(self)
        win.title("Add Installed App")
        win.geometry("540x500")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        
        # Sleek modern layout
        ctk.CTkLabel(
            win,
            text="Add Installed or Windows Store App",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        ).pack(pady=(18, 5))
        
        # Search box container with a modern rounded layout
        search_frame = ctk.CTkFrame(win, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=10)
        
        search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search installed apps (e.g. WhatsApp, Calculator)...",
            height=36,
            font=("Segoe UI", 12),
            corner_radius=8
        )
        search_entry.pack(fill="x", expand=True)
        search_entry.focus()
        
        # Loading/status container
        status_frame = ctk.CTkFrame(win, fg_color="transparent")
        status_frame.pack(pady=40)
        
        loading_lbl = ctk.CTkLabel(
            status_frame,
            text="Retrieving installed applications...",
            font=ctk.CTkFont(family="Segoe UI", size=13, slant="italic"),
            text_color="#94A3B8"
        )
        loading_lbl.pack()
        
        # Progress bar to make it look active and premium
        progress_bar = ctk.CTkProgressBar(status_frame, width=200, mode="indefinite")
        progress_bar.pack(pady=10)
        progress_bar.start()
        
        # Scrollable container for list (hidden initially)
        apps_scroll = ctk.CTkScrollableFrame(
            win, 
            fg_color="transparent",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569"
        )
        
        all_apps = []
        active_widgets = []
        
        def update_list(query=""):
            # Clear previous widgets safely
            for w in active_widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            active_widgets.clear()
            
            # Filter matches safely (avoid None lower attributes)
            query_clean = query.strip().lower()
            filtered = []
            for app in all_apps:
                name = (app.get("Name") or "")
                appid = (app.get("AppID") or "")
                if not query_clean or query_clean in name.lower() or query_clean in appid.lower():
                    filtered.append(app)
            
            # Slice to top 50 matches to keep UI blisteringly fast and prevent stuttering
            display_slice = filtered[:50]
            
            if not display_slice:
                no_match_frame = ctk.CTkFrame(apps_scroll, fg_color="transparent")
                no_match_frame.pack(pady=40)
                active_widgets.append(no_match_frame)
                
                ctk.CTkLabel(
                    no_match_frame, 
                    text="No matching applications found", 
                    font=("Segoe UI", 13, "bold"), 
                    text_color="#64748B"
                ).pack()
                ctk.CTkLabel(
                    no_match_frame, 
                    text="Try searching for a different keyword", 
                    font=("Segoe UI", 11), 
                    text_color="#475569"
                ).pack(pady=2)
                return
                
            for app in display_slice:
                name = app.get("Name", "Unknown App")
                appid = app.get("AppID", "")
                
                # Card row frame
                row = ctk.CTkFrame(
                    apps_scroll, 
                    fg_color="#1E293B", 
                    corner_radius=8, 
                    border_color="#334155", 
                    border_width=1
                )
                row.pack(fill="x", pady=4, ipady=4, padx=5)
                active_widgets.append(row)
                
                info_frame = ctk.CTkFrame(row, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True, padx=12, pady=2)
                
                display_name = name if len(name) <= 30 else name[:27] + "..."
                ctk.CTkLabel(
                    info_frame,
                    text=display_name,
                    font=("Segoe UI", 12, "bold"),
                    text_color="#F8FAFC",
                    anchor="w"
                ).pack(fill="x", anchor="w")
                
                display_id = appid if len(appid) <= 46 else appid[:43] + "..."
                ctk.CTkLabel(
                    info_frame,
                    text=display_id,
                    font=("Segoe UI", 9),
                    text_color="#64748B",
                    anchor="w"
                ).pack(fill="x", anchor="w")
                
                def make_add_cmd(app_name=name, app_id=appid):
                    def add_cmd():
                        if app_id.startswith("shell:") or app_id.lower().startswith("http://") or app_id.lower().startswith("https://") or app_id.startswith("steam:"):
                            target_val = app_id
                        elif ":" in app_id and (app_id.endswith(".exe") or app_id.endswith(".lnk") or os.path.exists(app_id)):
                            target_val = app_id
                        else:
                            target_val = f"shell:AppsFolder\\{app_id}"
                            
                        shortcut_id = app_name.lower().replace(" ", "_")
                        shortcut_id = "".join(c for c in shortcut_id if c.isalnum() or c == "_")
                        
                        existing = self.settings.get_deck_shortcuts()
                        if any(s['id'] == shortcut_id for s in existing):
                            shortcut_id += f"_{len(existing)}"
                            
                        self.settings.add_shortcut(shortcut_id, app_name, "app", target_val)
                        self.refresh_rules_ui()
                        win.destroy()
                        
                        from nexuslink.server.ws_server import sync_shortcuts_to_active_peers
                        sync_shortcuts_to_active_peers()
                    return add_cmd
                    
                add_btn = ctk.CTkButton(
                    row,
                    text="Add to Deck",
                    width=85,
                    height=26,
                    corner_radius=6,
                    fg_color="#2563EB",
                    hover_color="#1D4ED8",
                    font=("Segoe UI", 11, "bold"),
                    command=make_add_cmd(name, appid)
                )
                add_btn.pack(side="right", padx=10, pady=4)

        # Bind modern search change
        def on_search_change(event=None):
            update_list(search_entry.get())
            
        search_entry.bind("<KeyRelease>", on_search_change)
        
        def load_apps_thread():
            apps = get_installed_start_apps()
            self.ui_queue.put(lambda: display_apps(apps))
            
        def display_apps(apps):
            try:
                progress_bar.stop()
                status_frame.destroy()
            except Exception:
                pass
                
            apps_scroll.pack(fill="both", expand=True, padx=20, pady=(5, 20))
            
            if not apps:
                ctk.CTkLabel(
                    apps_scroll, 
                    text="No installed apps found.", 
                    font=("Segoe UI", 13), 
                    text_color="#94A3B8"
                ).pack(pady=40)
                return
                
            # Sort apps alphabetically, filtering out empty items safely
            sorted_apps = sorted(
                [a for a in apps if a.get("Name")],
                key=lambda x: (x.get("Name") or "").lower()
            )
            all_apps.extend(sorted_apps)
            
            # Initial list display (first 50 items)
            update_list()
            
        import threading
        threading.Thread(target=load_apps_thread, daemon=True).start()

    def refresh_rules_ui(self):
        if not hasattr(self, "shortcut_cards"):
            self.shortcut_cards = {}
        if not hasattr(self, "add_card_widget"):
            self.add_card_widget = None

        search_query = self.rules_search.get().strip().lower() if hasattr(self, "rules_search") else ""

        # Fetch shortcuts from settings
        shortcuts = self.settings.get_deck_shortcuts()
        
        # Build filtered list
        filtered_shortcuts = []
        if search_query:
            filtered_shortcuts = [s for s in shortcuts if search_query in s['label'].lower() or search_query in s['target'].lower() or search_query in s['type'].lower()]
        else:
            filtered_shortcuts = shortcuts

        # Set of current active filtered shortcut IDs
        active_ids = {s['id'] for s in filtered_shortcuts}

        # Hide any cards that are not in the current filtered list
        for sid, card in list(self.shortcut_cards.items()):
            if sid not in active_ids:
                card.grid_forget()

        # Destroy any cards that are completely deleted from the database
        all_ids = {s['id'] for s in shortcuts}
        for sid in list(self.shortcut_cards.keys()):
            if sid not in all_ids:
                self.shortcut_cards[sid].destroy()
                del self.shortcut_cards[sid]

        columns = 5

        # Layout the filtered cards
        for index, s in enumerate(filtered_shortcuts):
            sid = s['id']
            # If the card doesn't exist, create it once!
            if sid not in self.shortcut_cards:
                icon = get_shortcut_icon(s['label'], s['type'])
                
                # Closures to capture correct values
                def make_edit_cmd(item=s):
                    return lambda: self.edit_shortcut_window(item)
                    
                def make_remove_cmd(shortcut_id=sid):
                    return lambda: self.remove_shortcut(shortcut_id)

                card = ShortcutCard(
                    self.rules_scroll,
                    icon=icon,
                    title=s['label'],
                    target=s['target'],
                    shortcut_type=s['type'],
                    on_edit=make_edit_cmd(s),
                    on_remove=make_remove_cmd(sid)
                )
                self.shortcut_cards[sid] = card
            else:
                # Reuse existing card, but update title/target if they changed via edit
                card = self.shortcut_cards[sid]
                if card.title != s['label'] or card.target != s['target'] or card.shortcut_type != s['type']:
                    card.title = s['label']
                    card.target = s['target']
                    card.shortcut_type = s['type']
                    card.title_label.configure(text=card.truncate_text(s['label'], 16))
                    card.target_label.configure(text=card.truncate_text(s['target'], 20))
                    card.badge.configure(
                        text=s['type'].upper(),
                        fg_color="#205c9c" if s['type'].lower() == "app" else ("#e67e22" if s['type'].lower() == "steam" else "#2ecc71")
                    )
                    # Trigger async reload of the icon in case target changed
                    import threading
                    threading.Thread(target=card._load_icon_async, daemon=True).start()

            # Place the card in the grid
            row = index // columns
            col = index % columns
            card.grid(
                row=row,
                column=col,
                padx=10,
                pady=10,
                sticky="n"
            )

        # Place or create the "+" AddCard at the end
        add_index = len(filtered_shortcuts)
        add_row = add_index // columns
        add_col = add_index % columns

        if self.add_card_widget:
            self.add_card_widget.grid_forget()
        else:
            self.add_card_widget = AddCard(self.rules_scroll, command=self.show_add_shortcut_window)

        self.add_card_widget.grid(
            row=add_row,
            column=add_col,
            padx=10,
            pady=10,
            sticky="n"
        )

    def browse_exe(self, entry_widget):
        filepath = ctk.filedialog.askopenfilename(
            title="Select Executable",
            filetypes=[("Executables", "*.exe"), ("All Files", "*.*")]
        )
        if filepath:
            entry_widget.delete(0, ctk.END)
            entry_widget.insert(0, filepath)

    def truncate_text(self, text, max_len=48):
        if len(text) <= max_len:
            return text
        return text[:max_len-3] + "..."

    def edit_ai_app_window(self, old_name, old_exe):
        # Auto-detect type
        initial_type = "app"
        if old_exe.isdigit():
            initial_type = "steam"
        elif old_exe.startswith("http://") or old_exe.startswith("https://"):
            initial_type = "url"

        edit_win = ctk.CTkToplevel(self)
        edit_win.title(f"Edit AI App: {old_name.title()}")
        edit_win.geometry("450x260")
        edit_win.resizable(False, False)
        edit_win.attributes("-topmost", True)

        ctk.CTkLabel(edit_win, text=f"Edit AI App - {old_name.title()}", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(15, 10))

        # Inputs container
        form_frame = ctk.CTkFrame(edit_win, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(form_frame, text="App Name:").grid(row=0, column=0, sticky="w", pady=2)
        name_entry = ctk.CTkEntry(form_frame, width=280)
        name_entry.insert(0, old_name.title())
        name_entry.grid(row=0, column=1, padx=10, pady=2)

        ctk.CTkLabel(form_frame, text="Target/Path:").grid(row=1, column=0, sticky="w", pady=2)
        path_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        path_frame.grid(row=1, column=1, padx=10, pady=2)

        path_entry = ctk.CTkEntry(path_frame, width=210)
        path_entry.insert(0, old_exe)
        path_entry.pack(side="left", padx=(0, 5))
        browse_btn = ctk.CTkButton(path_frame, text="...", width=40, command=lambda: self.browse_exe(path_entry))
        browse_btn.pack(side="left")

        # Type row
        ctk.CTkLabel(form_frame, text="Type:").grid(row=2, column=0, sticky="w", pady=2)
        type_var = ctk.StringVar(value=initial_type)
        
        def on_type_change_edit(val):
            if val == "app":
                browse_btn.configure(state="normal")
                path_entry.configure(placeholder_text="Executable/Path (e.g. spotify.exe)")
            elif val == "steam":
                browse_btn.configure(state="disabled")
                path_entry.configure(placeholder_text="Steam App ID (e.g. 730)")
            elif val == "url":
                browse_btn.configure(state="disabled")
                path_entry.configure(placeholder_text="Web URL (e.g. https://youtube.com)")
                
        on_type_change_edit(initial_type)

        type_menu = ctk.CTkOptionMenu(
            form_frame, values=["app", "steam", "url"], 
            variable=type_var, command=on_type_change_edit, width=80
        )
        type_menu.grid(row=2, column=1, padx=10, pady=2, sticky="w")

        def save_changes():
            new_name = name_entry.get().strip()
            new_exe = path_entry.get().strip()
            if new_name and new_exe:
                self.settings.update_app(old_name, new_name, new_exe)
                self.refresh_rules_ui()
                edit_win.destroy()

        # Save / Cancel row
        btn_row = ctk.CTkFrame(edit_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="gray", hover_color="#555555", command=edit_win.destroy).pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="Save Changes", width=120, command=save_changes).pack(side="right", padx=5)

    def edit_shortcut_window(self, s_item):
        old_id = s_item["id"]
        old_label = s_item["label"]
        old_type = s_item["type"]
        old_target = s_item["target"]

        edit_win = ctk.CTkToplevel(self)
        edit_win.title(f"Edit Shortcut: {old_label}")
        edit_win.geometry("450x260")
        edit_win.resizable(False, False)
        edit_win.attributes("-topmost", True)

        ctk.CTkLabel(edit_win, text=f"Edit Shortcut - {old_label}", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(15, 10))

        # Inputs container
        form_frame = ctk.CTkFrame(edit_win, fg_color="transparent")
        form_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(form_frame, text="Label:").grid(row=0, column=0, sticky="w", pady=2)
        label_entry = ctk.CTkEntry(form_frame, width=280)
        label_entry.insert(0, old_label)
        label_entry.grid(row=0, column=1, padx=10, pady=2)

        ctk.CTkLabel(form_frame, text="Target/Path:").grid(row=1, column=0, sticky="w", pady=2)
        path_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        path_frame.grid(row=1, column=1, padx=10, pady=2)

        target_entry = ctk.CTkEntry(path_frame, width=210)
        target_entry.insert(0, old_target)
        target_entry.pack(side="left", padx=(0, 5))
        browse_btn = ctk.CTkButton(path_frame, text="...", width=40, command=lambda: self.browse_exe(target_entry))
        browse_btn.pack(side="left")

        # Type row
        ctk.CTkLabel(form_frame, text="Type:").grid(row=2, column=0, sticky="w", pady=2)
        type_var = ctk.StringVar(value=old_type)
        
        def on_type_change_edit(val):
            if val == "app":
                browse_btn.configure(state="normal")
            else:
                browse_btn.configure(state="disabled")
                
        on_type_change_edit(old_type)

        type_menu = ctk.CTkOptionMenu(
            form_frame, values=["app", "steam", "url"], 
            variable=type_var, command=on_type_change_edit, width=80
        )
        type_menu.grid(row=2, column=1, padx=10, pady=2, sticky="w")

        def save_changes():
            new_label = label_entry.get().strip()
            new_target = target_entry.get().strip()
            new_type = type_var.get()
            if new_label and new_target:
                self.settings.update_shortcut(old_id, new_label, new_type, new_target)
                self.refresh_rules_ui()
                edit_win.destroy()
                from nexuslink.server.ws_server import sync_shortcuts_to_active_peers
                sync_shortcuts_to_active_peers()

        # Save / Cancel row
        btn_row = ctk.CTkFrame(edit_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="gray", hover_color="#555555", command=edit_win.destroy).pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="Save Changes", width=120, command=save_changes).pack(side="right", padx=5)

    def add_ai_app(self):
        name = self.ai_name_entry.get().strip()
        exe = self.ai_exe_entry.get().strip()
        if name and exe:
            self.settings.add_app(name, exe)
            self.ai_name_entry.delete(0, ctk.END)
            self.ai_exe_entry.delete(0, ctk.END)
            self.ai_type_var.set("app")
            self.ai_browse_btn.configure(state="normal")
            self.ai_exe_entry.configure(placeholder_text="Executable/Path (e.g. spotify.exe)")
            self.refresh_rules_ui()

    def remove_ai_app(self, name):
        self.settings.remove_app(name)
        self.refresh_rules_ui()

    def add_shortcut(self):
        label = self.sc_name_entry.get().strip()
        target = self.sc_target_entry.get().strip()
        item_type = self.sc_type_var.get()
        if label and target:
            shortcut_id = label.lower().replace(" ", "_")
            self.settings.add_shortcut(shortcut_id, label, item_type, target)
            self.sc_name_entry.delete(0, ctk.END)
            self.sc_target_entry.delete(0, ctk.END)
            self.refresh_rules_ui()
            from nexuslink.server.ws_server import sync_shortcuts_to_active_peers
            sync_shortcuts_to_active_peers()

    def remove_shortcut(self, shortcut_id):
        self.settings.remove_shortcut(shortcut_id)
        self.refresh_rules_ui()
        from nexuslink.server.ws_server import sync_shortcuts_to_active_peers
        sync_shortcuts_to_active_peers()

    def check_single_instance(self):
        import ctypes
        self.lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except Exception:
                pass
        try:
            self.lock_socket.bind(("127.0.0.1", 47299))
            self.lock_socket.listen(5)
            
            # Start listener thread
            t = threading.Thread(target=self.listen_for_wake_up, daemon=True)
            t.start()
        except socket.error:
            # Wake up the existing instance
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.connect(("127.0.0.1", 47299))
                client.sendall(b"show")
                client.close()
                sys.exit(0)
            except Exception:
                # The port is likely stuck in TIME_WAIT from a crash,
                # so the other instance is dead. Continue launching.
                pass

    def listen_for_wake_up(self):
        while True:
            try:
                conn, addr = self.lock_socket.accept()
                data = conn.recv(1024)
                if b"show" in data:
                    self.after(0, self.show_window)
                conn.close()
            except Exception:
                break

    def start_backend(self):
        asyncio.run(run_backend(47200))

    def setup_tray(self):
        image = create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self.show_window, default=True),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("DeviceLink", image, "DeviceLink Agent", menu, action=lambda icon, item=None: self.show_window())
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.withdraw()
        self.update_telemetry_sync_state()

    def show_window(self):
        self.after(0, self.deiconify)
        self.after(50, lambda: self.attributes("-topmost", True))
        self.after(100, lambda: self.attributes("-topmost", False))
        self.after(150, self.focus_force)
        self.after(200, lambda: self.refresh_connection_status(force=True))
        self.after(250, self.trigger_status_animation)
        self.after(300, self.update_telemetry_sync_state)

    def quit_app(self):
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        self.tray_icon.stop()
        self.quit()
        sys.exit(0)

    def is_run_on_startup_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "DeviceLink"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            val, _ = winreg.QueryValueEx(key, app_name)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def toggle_startup(self) -> None:
        if sys.platform != "win32":
            return
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "DeviceLink"
        
        # Check active settings variable first, falling back to current state
        if hasattr(self, "settings_startup_var"):
            enabled = self.settings_startup_var.get()
        else:
            enabled = self.is_run_on_startup_enabled()
        
        # Check minimized setting
        minimized = False
        if hasattr(self, "settings_minimized_var"):
            minimized = self.settings_minimized_var.get()
        else:
            minimized = self.settings.settings.get("start_minimized_on_launch", False)
        
        if getattr(sys, 'frozen', False):
            exe_path = f'"{sys.executable}"'
        else:
            script_path = os.path.abspath(sys.argv[0])
            exe_path = f'"{sys.executable}" "{script_path}"'
            
        if minimized:
            exe_path += " --minimized"
            
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enabled:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                print(f"[Console] Enabled auto-start on startup: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    print("[Console] Disabled auto-start on startup.")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Console] Failed to update startup configuration: {e}")

    def open_settings_window(self):
        # Prevent opening duplicate settings window
        if hasattr(self, "settings_win") and self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus()
            return
            
        self.settings_win = ctk.CTkToplevel(self)
        self.settings_win.title("Preferences & API Settings")
        self.settings_win.geometry("500x560")
        self.settings_win.resizable(False, False)
        
        # Force transient and topmost so it sits nicely in front of main dashboard
        self.settings_win.transient(self)
        self.settings_win.attributes("-topmost", True)
        
        # Header
        ctk.CTkLabel(
            self.settings_win, 
            text="Preferences & API Config", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=20, pady=(20, 10))
        
        # Form Container (Scrollable Frame to prevent window truncation)
        form_frame = ctk.CTkScrollableFrame(self.settings_win)
        form_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        
        # OpenRouter API Key
        ctk.CTkLabel(
            form_frame, 
            text="OpenRouter API Key:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 2))
        
        self.api_key_entry = ctk.CTkEntry(
            form_frame, 
            width=430, 
            placeholder_text="sk-or-v1-...",
            show="*"
        )
        # Check settings manager
        current_key = self.settings.get_openrouter_api_key()
        self.api_key_entry.insert(0, current_key)
        self.api_key_entry.pack(anchor="w", padx=15, pady=(0, 10))
        
        # OpenRouter Model Name
        ctk.CTkLabel(
            form_frame, 
            text="OpenRouter Model Name:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=15, pady=(0, 2))
        
        self.model_entry = ctk.CTkEntry(
            form_frame, 
            width=430, 
            placeholder_text="google/gemini-2.5-flash"
        )
        current_model = self.settings.get_openrouter_model()
        self.model_entry.insert(0, current_model)
        self.model_entry.pack(anchor="w", padx=15, pady=(0, 15))
        
        # Allowed Launch Directories
        ctk.CTkLabel(
            form_frame, 
            text="Allowed Launch Directories (semicolon separated):", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=15, pady=(0, 2))
        
        self.dirs_entry = ctk.CTkEntry(
            form_frame, 
            width=430, 
            placeholder_text="C:\\Games; D:\\; E:\\"
        )
        current_dirs = "; ".join(self.settings.settings.get("allowed_launch_dirs", []))
        self.dirs_entry.insert(0, current_dirs)
        self.dirs_entry.pack(anchor="w", padx=15, pady=(0, 15))

        # Divider
        divider = ctk.CTkFrame(form_frame, height=2, fg_color="#2D3748")
        divider.pack(fill="x", padx=15, pady=10)
        
        # System Preferences
        ctk.CTkLabel(
            form_frame, 
            text="System Preferences:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=15, pady=(0, 5))
        
        self.settings_startup_var = ctk.BooleanVar(value=self.is_run_on_startup_enabled())
        self.settings_startup_switch = ctk.CTkSwitch(
            form_frame, 
            text="Launch DeviceLink automatically on system startup", 
            variable=self.settings_startup_var,
            command=self.toggle_startup
        )
        self.settings_startup_switch.pack(anchor="w", padx=15, pady=(5, 5))
        
        self.settings_minimized_var = ctk.BooleanVar(value=self.settings.settings.get("start_minimized_on_launch", False))
        self.settings_minimized_switch = ctk.CTkSwitch(
            form_frame, 
            text="Start minimized to system tray on Windows launch", 
            variable=self.settings_minimized_var,
            command=self.toggle_startup
        )
        self.settings_minimized_switch.pack(anchor="w", padx=15, pady=(5, 15))

        # Divider 2
        divider2 = ctk.CTkFrame(form_frame, height=2, fg_color="#2D3748")
        divider2.pack(fill="x", padx=15, pady=10)
        
        # Updates Section
        ctk.CTkLabel(
            form_frame, 
            text="App Updates:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=15, pady=(0, 2))
        
        self.settings_update_lbl = ctk.CTkLabel(
            form_frame, 
            text=f"Current Version: v{VERSION}", 
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.settings_update_lbl.pack(anchor="w", padx=15, pady=(0, 5))
        
        self.settings_check_update_btn = ctk.CTkButton(
            form_frame, 
            text="Check for Updates", 
            width=150, 
            command=self.check_for_updates_manually
        )
        self.settings_check_update_btn.pack(anchor="w", padx=15, pady=(5, 15))
        
        # Buttons Row
        btn_row = ctk.CTkFrame(self.settings_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 15))
        
        cancel_btn = ctk.CTkButton(
            btn_row, 
            text="Cancel", 
            width=80, 
            fg_color="gray", 
            hover_color="#555555", 
            command=self.settings_win.destroy
        )
        cancel_btn.pack(side="right", padx=(5, 0))
        
        save_btn = ctk.CTkButton(
            btn_row, 
            text="Save Settings", 
            width=120, 
            command=self.save_settings_preferences
        )
        save_btn.pack(side="right")
        
    def save_settings_preferences(self):
        new_key = self.api_key_entry.get().strip()
        new_model = self.model_entry.get().strip()
        raw_dirs = self.dirs_entry.get().strip()
        
        # Parse directories list
        dirs_list = [d.strip() for d in raw_dirs.split(";") if d.strip()]
        
        self.settings.update_openrouter_settings(new_key, new_model)
        self.settings.settings["allowed_launch_dirs"] = dirs_list
        if hasattr(self, "settings_minimized_var"):
            self.settings.settings["start_minimized_on_launch"] = self.settings_minimized_var.get()
        self.settings.save()
        
        print("[Console] Settings saved successfully.")
        self.settings_win.destroy()

    def _build_agent_test_tab(self):
        # Container frame
        test_frame = ctk.CTkFrame(self.tab_agent_test, fg_color="transparent")
        test_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Center container for the input controls
        input_container = ctk.CTkFrame(test_frame, fg_color="transparent")
        input_container.pack(fill="x", pady=(10, 20), padx=50)

        self.prompt_entry = ctk.CTkEntry(
            input_container, 
            placeholder_text="Type an AI command (e.g., open youtube, sync clipboard...)",
            height=40,
            font=ctk.CTkFont(size=13)
        )
        self.prompt_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.prompt_entry.bind("<Return>", lambda event: self.send_test_prompt())

        self.send_prompt_btn = ctk.CTkButton(
            input_container, 
            text="Run Command", 
            width=120, 
            height=40,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.send_test_prompt
        )
        self.send_prompt_btn.pack(side="left", padx=(0, 10))

        self.cancel_prompt_btn = ctk.CTkButton(
            input_container,
            text="Cancel",
            width=80,
            height=40,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            command=self.cancel_test_prompt
        )
        self.cancel_prompt_btn.pack(side="left", padx=(0, 10))
        self.cancel_prompt_btn.configure(state="disabled")

        self.chat_history_btn = ctk.CTkButton(
            input_container,
            text="Chat History",
            width=110,
            height=40,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self.show_agent_chat_history
        )
        self.chat_history_btn.pack(side="left")

        # Response text box (placed dynamically during streaming)
        self.response_box = ctk.CTkTextbox(
            test_frame,
            fg_color="#0e131b",
            border_width=1,
            border_color="#1e293b",
            font=ctk.CTkFont(size=13, family="Segoe UI"),
            wrap="word"
        )

        # Agent Animation Canvas
        self.agent_canvas = AgentCanvas(
            test_frame
        )
        self.agent_canvas.response_box = self.response_box
        self.agent_canvas.pack(fill="both", expand=True)
        self.agent_canvas.set_state("idle")
        self.agent_canvas.animate()

    def send_test_prompt(self):
        prompt = self.prompt_entry.get().strip()
        if not prompt:
            return

        self.prompt_entry.delete(0, ctk.END)
        self.send_prompt_btn.configure(state="disabled")
        self.cancel_prompt_btn.configure(state="normal")
        
        # Add to history
        self.agent_chat_history.append({
            "prompt": prompt,
            "result": "Thinking...",
            "timestamp": time.strftime("%H:%M:%S")
        })

        # Start thinking animation
        self.agent_canvas.start_thinking()
        self.current_agent_future = None

        # Run in worker thread so the UI doesn't freeze during API request
        def worker():
            try:
                # Import agent here to avoid circular imports or early setup issues
                from nexuslink.server.agent_orchestrator import agent
                import nexuslink.server.ws_server as ws_server
                
                # Check if the main backend event loop is running
                loop = ws_server._loop
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(agent.execute_command(prompt), loop)
                    self.current_agent_future = future
                    result = future.result()
                else:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    task = loop.create_task(agent.execute_command(prompt))
                    self.current_agent_future = task
                    result = loop.run_until_complete(task)
                    loop.close()
                
                # Update UI in main thread safely
                self.after(0, lambda: self.handle_agent_success(prompt, result))
            except Exception as e:
                err_name = e.__class__.__name__
                if "cancel" in err_name.lower() or "cancel" in str(e).lower():
                    self.after(0, self.handle_agent_cancelled)
                else:
                    self.after(0, lambda: self.handle_agent_error(prompt, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_test_prompt(self):
        if hasattr(self, "current_agent_future") and self.current_agent_future:
            try:
                self.current_agent_future.cancel()
            except Exception:
                pass
        self.handle_agent_cancelled()

    def handle_agent_cancelled(self):
        if self.agent_chat_history:
            self.agent_chat_history[-1]["result"] = "[Cancelled by User]"
        self.agent_canvas.show_response("Request cancelled by user.", is_error=True)
        self.send_prompt_btn.configure(state="normal")
        self.cancel_prompt_btn.configure(state="disabled")

    def handle_agent_success(self, prompt, result):
        if self.agent_chat_history:
            self.agent_chat_history[-1]["result"] = result
        self.agent_canvas.show_response(result, is_error=False)
        self.send_prompt_btn.configure(state="normal")
        self.cancel_prompt_btn.configure(state="disabled")

    def handle_agent_error(self, prompt, error_msg):
        if self.agent_chat_history:
            self.agent_chat_history[-1]["result"] = f"[Error] {error_msg}"
        self.agent_canvas.show_response(f"An error occurred:\n\n{error_msg}", is_error=True)
        self.send_prompt_btn.configure(state="normal")
        self.cancel_prompt_btn.configure(state="disabled")

    def show_agent_chat_history(self):
        history_win = ctk.CTkToplevel(self)
        history_win.title("AI Agent Command History")
        history_win.geometry("600x500")
        history_win.configure(fg_color="#0b0f14")
        
        # Keep on top of parent window on Windows
        history_win.transient(self)
        
        # Lift and grab focus
        history_win.lift()
        history_win.focus_force()
        
        ctk.CTkLabel(
            history_win,
            text="Command History",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="white"
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        history_box = ctk.CTkTextbox(
            history_win,
            fg_color="#0e131b",
            border_width=0,
            font=ctk.CTkFont(size=12, family="Segoe UI"),
            wrap="word"
        )
        history_box.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        if not self.agent_chat_history:
            history_box.insert("end", "No commands executed in this session yet.\n")
        else:
            for entry in self.agent_chat_history:
                history_box.insert("end", f"⏰ [{entry['timestamp']}] Command:\n")
                history_box.insert("end", f"{entry['prompt']}\n\n")
                history_box.insert("end", "🤖 Response:\n")
                history_box.insert("end", f"{entry['result']}\n")
                history_box.insert("end", "─" * 65 + "\n\n")
                
        history_box.configure(state="disabled")

    def _build_calls_tab(self):
        self.raw_contacts = [] # Store raw synced contacts
        
        # Horizontal Split container
        container = ctk.CTkFrame(self.tab_calls, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # ── LEFT PANEL: DIALER ──
        dialer_panel = ctk.CTkFrame(
            container,
            fg_color="#0F172A",
            width=340,
            corner_radius=16,
            border_width=1,
            border_color="#1E293B"
        )
        dialer_panel.pack(side="left", fill="both", padx=(0, 10), pady=10)
        dialer_panel.pack_propagate(False)

        # Info Button at top-right of Dialer
        info_btn = ctk.CTkButton(
            dialer_panel,
            text="ℹ",
            width=28,
            height=28,
            corner_radius=14,
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#38BDF8",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.show_telephony_info_modal
        )
        info_btn.place(x=295, y=12)

        # Title
        dialer_title = ctk.CTkLabel(
            dialer_panel,
            text="Dialer",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F8FAFC"
        )
        dialer_title.pack(anchor="w", padx=20, pady=(20, 5))

        # Bluetooth Status Indicator
        self.bt_status_frame = ctk.CTkFrame(dialer_panel, fg_color="#1E293B", height=28, corner_radius=6)
        self.bt_status_frame.pack(anchor="w", padx=20, pady=(0, 10))
        
        self.bt_status_dot = ctk.CTkLabel(
            self.bt_status_frame, 
            text="●", 
            text_color="#EF4444", 
            font=ctk.CTkFont(size=12)
        )
        self.bt_status_dot.pack(side="left", padx=(10, 5))
        
        self.bt_status_text = ctk.CTkLabel(
            self.bt_status_frame, 
            text="Bluetooth HFP: Disconnected", 
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#CBD5E1"
        )
        self.bt_status_text.pack(side="left", padx=(0, 10))

        # Number Display
        self.phone_entry = ctk.CTkEntry(
            dialer_panel,
            placeholder_text="Enter number",
            font=ctk.CTkFont(size=22, weight="bold"),
            justify="center",
            height=48,
            fg_color="#020617",
            border_color="#1E293B",
            text_color="#F8FAFC",
            corner_radius=8
        )
        self.phone_entry.pack(fill="x", padx=20, pady=(0, 15))

        # Keypad Grid Frame
        keypad_frame = ctk.CTkFrame(dialer_panel, fg_color="transparent")
        keypad_frame.pack(pady=5)

        # Keys
        keys = [
            ("1", "2", "3"),
            ("4", "5", "6"),
            ("7", "8", "9"),
            ("*", "0", "#")
        ]

        for r_idx, row in enumerate(keys):
            for c_idx, key in enumerate(row):
                btn = ctk.CTkButton(
                    keypad_frame,
                    text=key,
                    width=70,
                    height=48,
                    corner_radius=24,
                    font=ctk.CTkFont(size=18, weight="bold"),
                    fg_color="#1E293B",
                    hover_color="#334155",
                    text_color="#CBD5E1",
                    command=lambda k=key: self._dial_key_press(k)
                )
                btn.grid(row=r_idx, column=c_idx, padx=6, pady=5)

        # Action Buttons row (Clear, Call, Backspace)
        action_frame = ctk.CTkFrame(keypad_frame, fg_color="transparent")
        action_frame.grid(row=4, column=0, columnspan=3, pady=10, sticky="ew")

        clear_btn = ctk.CTkButton(
            action_frame,
            text="C",
            width=54,
            height=48,
            corner_radius=24,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#374151",
            hover_color="#4B5563",
            text_color="#9CA3AF",
            command=self._dial_clear
        )
        clear_btn.pack(side="left", padx=(6, 5))

        call_btn = ctk.CTkButton(
            action_frame,
            text="📞",
            width=80,
            height=48,
            corner_radius=24,
            font=ctk.CTkFont(size=20),
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#F8FAFC",
            command=self.dial_call
        )
        call_btn.pack(side="left", padx=5, fill="x", expand=True)

        backspace_btn = ctk.CTkButton(
            action_frame,
            text="⌫",
            width=54,
            height=48,
            corner_radius=24,
            font=ctk.CTkFont(size=16),
            fg_color="#374151",
            hover_color="#4B5563",
            text_color="#9CA3AF",
            command=self._dial_backspace
        )
        backspace_btn.pack(side="left", padx=(5, 6))

        # ── RIGHT PANEL: CONTACTS ──
        contacts_panel = ctk.CTkFrame(
            container,
            fg_color="#1E293B",
            corner_radius=16,
            border_width=1,
            border_color="#334155"
        )
        contacts_panel.pack(side="right", fill="both", expand=True, padx=(10, 0), pady=10)

        # Header Title
        contacts_title = ctk.CTkLabel(
            contacts_panel,
            text="Synced Contacts",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F8FAFC"
        )
        contacts_title.pack(anchor="w", padx=20, pady=(20, 10))

        # Search Box
        self.search_entry = ctk.CTkEntry(
            contacts_panel,
            placeholder_text="🔍 Search contacts by name or number...",
            font=ctk.CTkFont(size=13),
            height=36,
            fg_color="#0F172A",
            border_color="#334155",
            text_color="#F8FAFC",
            corner_radius=8
        )
        self.search_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.search_entry.bind("<KeyRelease>", self._on_search_change)

        # Scrollable list container
        self.contacts_scroll_frame = ctk.CTkScrollableFrame(
            contacts_panel,
            fg_color="transparent",
            label_text=""
        )
        self.contacts_scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Initial Empty State
        self.display_empty_contacts_state()

    def _on_search_change(self, event):
        # Cancel any pending search query to debounce inputs
        if hasattr(self, "_search_after_id") and self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._run_debounced_search)

    def _run_debounced_search(self):
        self._search_after_id = None
        query = self.search_entry.get().strip()
        self.filter_and_populate_contacts(query)

    def display_empty_contacts_state(self, message="No contacts synced yet.\nPair your phone via Bluetooth & Wi-Fi to sync your contacts."):
        # Clear frame first
        for widget in self.contacts_scroll_frame.winfo_children():
            widget.destroy()

        empty_label = ctk.CTkLabel(
            self.contacts_scroll_frame,
            text=message,
            font=ctk.CTkFont(size=14),
            text_color="gray",
            justify="center"
        )
        empty_label.pack(expand=True, pady=100)

    def handle_sync_contacts(self, contacts):
        """Called when a 'sync_contacts' WebSocket payload is received."""
        self.raw_contacts = contacts
        self.filter_and_populate_contacts("")

    def filter_and_populate_contacts(self, query=""):
        # Clear current list
        for widget in self.contacts_scroll_frame.winfo_children():
            widget.destroy()

        filtered_contacts = []
        q = query.lower()
        for c in self.raw_contacts:
            name = c.get("name", "")
            number = c.get("number", "")
            if not q or (q in name.lower() or q in number.lower()):
                filtered_contacts.append(c)

        if not filtered_contacts:
            if not self.raw_contacts:
                self.display_empty_contacts_state()
            else:
                self.display_empty_contacts_state("No contacts match your search query.")
            return

        # Sort contacts alphabetically by name
        filtered_contacts.sort(key=lambda x: x.get("name", "").lower())

        total_matches = len(filtered_contacts)
        max_display = 50
        contacts_to_render = filtered_contacts[:max_display]

        # Render list
        for contact in contacts_to_render:
            name = contact.get("name", "Unknown")
            number = contact.get("number", "Unknown Number")

            # Contact Card Row Frame
            card = ctk.CTkFrame(
                self.contacts_scroll_frame,
                fg_color="#0F172A",
                corner_radius=10,
                border_width=1,
                border_color="#1E293B"
            )
            card.pack(fill="x", padx=5, pady=4)

            # Avatar Circle (Initials)
            initial = name[0].upper() if name else "?"
            avatar_frame = ctk.CTkFrame(
                card,
                width=36,
                height=36,
                corner_radius=18,
                fg_color="#38BDF8"  # Beautiful cyan circle
            )
            avatar_frame.pack(side="left", padx=10, pady=8)
            avatar_frame.pack_propagate(False)

            avatar_label = ctk.CTkLabel(
                avatar_frame,
                text=initial,
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#0F172A"
            )
            avatar_label.pack(expand=True)

            # Contact Details
            details_frame = ctk.CTkFrame(card, fg_color="transparent")
            details_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)

            name_lbl = ctk.CTkLabel(
                details_frame,
                text=name,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#F8FAFC"
            )
            name_lbl.pack(anchor="w", pady=(2, 0))

            num_lbl = ctk.CTkLabel(
                details_frame,
                text=number,
                font=ctk.CTkFont(size=11),
                text_color="#94A3B8"
            )
            num_lbl.pack(anchor="w", pady=(0, 2))

            # Action Call Button (Green)
            call_btn = ctk.CTkButton(
                card,
                text="📞",
                width=38,
                height=36,
                corner_radius=8,
                fg_color="#10B981",
                hover_color="#059669",
                font=ctk.CTkFont(size=14),
                command=lambda num=number: self.dial_contact(num)
            )
            call_btn.pack(side="right", padx=12, pady=8)

        if total_matches > max_display:
            more_label = ctk.CTkLabel(
                self.contacts_scroll_frame,
                text=f"Showing top {max_display} of {total_matches} contacts. Type more to filter...",
                font=ctk.CTkFont(size=12, slant="italic"),
                text_color="#94A3B8",
                pady=10
            )
            more_label.pack(fill="x", padx=5)

    def dial_contact(self, number):
        self.phone_entry.delete(0, ctk.END)
        self.phone_entry.insert(0, number)
        self.dial_call()

    def _dial_key_press(self, key):
        self.phone_entry.insert(ctk.END, key)

    def _dial_backspace(self):
        curr = self.phone_entry.get()
        if curr:
            self.phone_entry.delete(len(curr) - 1)

    def _dial_clear(self):
        self.phone_entry.delete(0, ctk.END)

    def show_telephony_info_modal(self):
        # Create a beautiful information modal
        info_win = ctk.CTkToplevel(self)
        info_win.title("Bluetooth Telephony Instructions")
        info_win.geometry("450x330")
        info_win.resizable(False, False)
        info_win.attributes("-topmost", True)

        # Center the window
        screen_width = info_win.winfo_screenwidth()
        screen_height = info_win.winfo_screenheight()
        x = (screen_width // 2) - 225
        y = (screen_height // 2) - 165
        info_win.geometry(f"+{x}+{y}")

        title = ctk.CTkLabel(
            info_win,
            text="Bluetooth Calling Setup",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F8FAFC"
        )
        title.pack(pady=(20, 15))

        instructions = (
            "To make and receive phone calls directly from your PC:\n\n"
            "• Open Windows Bluetooth settings.\n"
            "• Pair your PC with your Android phone.\n"
            "• Go to properties of your paired phone and verify 'Phone audio' (Hands-Free Profile / HFP) is active.\n"
            "• Incoming calls will show a pop-up overlay where you can answer or decline calls instantly.\n"
            "• Outgoing call audio is automatically routed to your PC's mic & speaker."
        )
        
        info_text = ctk.CTkLabel(
            info_win,
            text=instructions,
            justify="left",
            font=ctk.CTkFont(size=13),
            text_color="#CBD5E1",
            wraplength=390
        )
        info_text.pack(padx=25, pady=10)

        close_btn = ctk.CTkButton(
            info_win,
            text="Got it",
            width=120,
            command=info_win.destroy
        )
        close_btn.pack(pady=(15, 20))

    def dial_call(self):
        number = self.phone_entry.get().strip()
        if not number:
            return
        
        from nexuslink.server.ws_server import get_active_peers, send_message_to_all_peers_sync
        if not get_active_peers():
            from tkinter import messagebox
            messagebox.showwarning("No Connection", "Please connect your Android phone first via the QR code.")
            return

        send_message_to_all_peers_sync("make_call", {"number": number})

    def show_call_overlay(self, number, name):
        # Close any existing call overlay first to be safe
        if hasattr(self, 'call_overlay_window') and self.call_overlay_window and self.call_overlay_window.winfo_exists():
            self.call_overlay_window.destroy()

        self.call_overlay_window = ctk.CTkToplevel(self)
        self.call_overlay_window.title("Incoming Call")
        self.call_overlay_window.geometry("340x220")
        self.call_overlay_window.resizable(False, False)
        self.call_overlay_window.attributes("-topmost", True)
        
        # Center the window on the screen
        screen_width = self.call_overlay_window.winfo_screenwidth()
        screen_height = self.call_overlay_window.winfo_screenheight()
        x = (screen_width // 2) - 170
        y = (screen_height // 2) - 110
        self.call_overlay_window.geometry(f"+{x}+{y}")

        # Top banner / title
        title_lbl = ctk.CTkLabel(
            self.call_overlay_window,
            text="📱 INCOMING CALL",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38BDF8"
        )
        title_lbl.pack(pady=(15, 5))

        # Caller Name
        self.caller_name_lbl = ctk.CTkLabel(
            self.call_overlay_window,
            text=name,
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.caller_name_lbl.pack(pady=(5, 2))

        # Caller Number
        self.caller_num_lbl = ctk.CTkLabel(
            self.call_overlay_window,
            text=number,
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        self.caller_num_lbl.pack(pady=(0, 15))

        # Buttons Frame
        self.call_btn_frame = ctk.CTkFrame(self.call_overlay_window, fg_color="transparent")
        self.call_btn_frame.pack(fill="x", padx=30, pady=10)

        # Answer Button (Green)
        self.answer_btn = ctk.CTkButton(
            self.call_btn_frame,
            text="📞 Answer",
            width=120,
            height=40,
            fg_color="#10B981",
            hover_color="#059669",
            command=self.answer_call
        )
        self.answer_btn.pack(side="left", padx=5)

        # Decline Button (Red)
        self.decline_btn = ctk.CTkButton(
            self.call_btn_frame,
            text="❌ Decline",
            width=120,
            height=40,
            fg_color="#EF4444",
            hover_color="#DC2626",
            command=self.decline_call
        )
        self.decline_btn.pack(side="right", padx=5)

    def answer_call(self):
        from nexuslink.server.ws_server import send_message_to_all_peers_sync
        send_message_to_all_peers_sync("call_action", {"action": "answer"})
        # Update HUD state to "Connected" with a Hang Up button
        self.answer_btn.pack_forget()
        self.decline_btn.pack_forget()
        
        self.call_overlay_window.title("Active Call")
        self.caller_num_lbl.configure(text="In Call")
        
        self.hangup_btn = ctk.CTkButton(
            self.call_btn_frame,
            text="🛑 Hang Up",
            width=240,
            height=40,
            fg_color="#EF4444",
            hover_color="#DC2626",
            command=self.hangup_call
        )
        self.hangup_btn.pack(padx=20)

    def decline_call(self):
        from nexuslink.server.ws_server import send_message_to_all_peers_sync
        send_message_to_all_peers_sync("call_action", {"action": "decline"})
        if hasattr(self, 'call_overlay_window') and self.call_overlay_window:
            self.call_overlay_window.destroy()
            self.call_overlay_window = None

    def hangup_call(self):
        from nexuslink.server.ws_server import send_message_to_all_peers_sync
        send_message_to_all_peers_sync("call_action", {"action": "hangup"})
        if hasattr(self, 'call_overlay_window') and self.call_overlay_window:
            self.call_overlay_window.destroy()
            self.call_overlay_window = None

    def handle_call_status_change(self, status):
        """Handle status updates like 'idle' (hangup) from the phone."""
        if status == "idle":
            if hasattr(self, 'call_overlay_window') and self.call_overlay_window and self.call_overlay_window.winfo_exists():
                self.call_overlay_window.destroy()
                self.call_overlay_window = None
        elif status == "offhook":
            # If the user answered the call on the phone physically, we also update the overlay state
            if hasattr(self, 'call_overlay_window') and self.call_overlay_window and self.call_overlay_window.winfo_exists():
                if hasattr(self, 'answer_btn') and self.answer_btn.winfo_exists():
                    self.answer_btn.pack_forget()
                if hasattr(self, 'decline_btn') and self.decline_btn.winfo_exists():
                    self.decline_btn.pack_forget()
                
                self.call_overlay_window.title("Active Call")
                self.caller_num_lbl.configure(text="In Call")
                
                if not hasattr(self, 'hangup_btn') or not self.hangup_btn.winfo_exists():
                    self.hangup_btn = ctk.CTkButton(
                        self.call_btn_frame,
                        text="🛑 Hang Up",
                        width=240,
                        height=40,
                        fg_color="#EF4444",
                        hover_color="#DC2626",
                        command=self.hangup_call
                    )
                    self.hangup_btn.pack(padx=20)

    def handle_bt_status_change(self, connected):
        """Handle Bluetooth status updates from the phone."""
        if hasattr(self, 'bt_status_dot') and hasattr(self, 'bt_status_text'):
            if connected:
                self.bt_status_dot.configure(text_color="#10B981") # Green
                self.bt_status_text.configure(text="Bluetooth HFP: Connected")
            else:
                self.bt_status_dot.configure(text_color="#EF4444") # Red
                self.bt_status_text.configure(text="Bluetooth HFP: Disconnected")


    def fetch_latest_release(self):
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'DeviceLink-Updater/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"[Updater] Error fetching latest release: {e}")
        return None

    def check_for_updates_silently(self):
        release = self.fetch_latest_release()
        if not release:
            return
        
        latest_tag = release.get("tag_name", "")
        if not latest_tag:
            return
            
        if is_newer_version(VERSION, latest_tag):
            assets = release.get("assets", [])
            download_url = None
            for asset in assets:
                name = asset.get("name", "")
                if name.lower() == "devicelink.exe":
                    download_url = asset.get("browser_download_url")
                    break
            
            if download_url:
                self.after(0, lambda: self.show_update_available_dialog(latest_tag, download_url, release.get("body", "")))

    def check_for_updates_manually(self):
        if not hasattr(self, "settings_check_update_btn") or not hasattr(self, "settings_update_lbl"):
            return
        self.settings_check_update_btn.configure(state="disabled", text="Checking...")
        self.settings_update_lbl.configure(text="Checking for updates...")
        
        def worker():
            release = self.fetch_latest_release()
            
            def update_ui():
                self.settings_check_update_btn.configure(state="normal", text="Check for Updates")
                if not release:
                    self.settings_update_lbl.configure(text=f"Current Version: v{VERSION}\nFailed to contact update server.")
                    from tkinter import messagebox
                    messagebox.showerror("Update Error", "Failed to check for updates. Please check your internet connection.")
                    return
                
                latest_tag = release.get("tag_name", "")
                if not latest_tag:
                    self.settings_update_lbl.configure(text=f"Current Version: v{VERSION}\nInvalid server response.")
                    return
                
                if is_newer_version(VERSION, latest_tag):
                    assets = release.get("assets", [])
                    download_url = None
                    for asset in assets:
                        name = asset.get("name", "")
                        if name.lower() == "devicelink.exe":
                            download_url = asset.get("browser_download_url")
                            break
                    
                    if download_url:
                        self.settings_update_lbl.configure(text=f"Update available: {latest_tag}")
                        self.show_update_available_dialog(latest_tag, download_url, release.get("body", ""))
                    else:
                        self.settings_update_lbl.configure(text=f"Current Version: v{VERSION}\nNo compatible asset found in release.")
                else:
                    self.settings_update_lbl.configure(text=f"Current Version: v{VERSION} (Up to date)")
                    from tkinter import messagebox
                    messagebox.showinfo("Up to Date", f"You are running the latest version (v{VERSION}).")
            
            self.after(0, update_ui)
            
        threading.Thread(target=worker, daemon=True).start()

    def show_update_available_dialog(self, latest_tag, download_url, release_notes):
        update_win = ctk.CTkToplevel(self)
        update_win.title("Update Available")
        update_win.geometry("450x400")
        update_win.resizable(False, False)
        update_win.attributes("-topmost", True)
        update_win.transient(self)
        
        # Center it
        screen_width = update_win.winfo_screenwidth()
        screen_height = update_win.winfo_screenheight()
        x = (screen_width // 2) - 225
        y = (screen_height // 2) - 200
        update_win.geometry(f"+{x}+{y}")
        
        title = ctk.CTkLabel(
            update_win,
            text=f"New Version Available: {latest_tag}",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#38BDF8"
        )
        title.pack(pady=(20, 10))
        
        desc = ctk.CTkLabel(
            update_win,
            text=f"A new version of DeviceLink is available (you have v{VERSION}).\nWould you like to download and install it now?",
            font=ctk.CTkFont(size=12),
            text_color="#F8FAFC",
            justify="center"
        )
        desc.pack(padx=20, pady=(0, 15))
        
        notes_frame = ctk.CTkScrollableFrame(update_win, height=120, width=400)
        notes_frame.pack(padx=20, pady=(0, 20))
        
        notes_title = ctk.CTkLabel(
            notes_frame,
            text="Release Notes:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray",
            anchor="w"
        )
        notes_title.pack(fill="x", padx=5)
        
        notes_text = ctk.CTkLabel(
            notes_frame,
            text=release_notes if release_notes else "No release notes provided.",
            font=ctk.CTkFont(size=11),
            text_color="#CBD5E1",
            justify="left",
            wraplength=360,
            anchor="w"
        )
        notes_text.pack(fill="x", padx=5, pady=5)
        
        btn_frame = ctk.CTkFrame(update_win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        later_btn = ctk.CTkButton(
            btn_frame,
            text="Later",
            width=100,
            fg_color="gray",
            hover_color="#555555",
            command=update_win.destroy
        )
        later_btn.pack(side="left", padx=(0, 10))
        
        def do_update():
            update_win.destroy()
            self.show_download_progress_dialog(download_url, latest_tag)
            
        update_btn = ctk.CTkButton(
            btn_frame,
            text="Download & Install",
            width=180,
            command=do_update
        )
        update_btn.pack(side="right", fill="x", expand=True)

    def show_download_progress_dialog(self, download_url, latest_tag):
        progress_win = ctk.CTkToplevel(self)
        progress_win.title("Downloading Update")
        progress_win.geometry("380x160")
        progress_win.resizable(False, False)
        progress_win.attributes("-topmost", True)
        progress_win.transient(self)
        
        screen_width = progress_win.winfo_screenwidth()
        screen_height = progress_win.winfo_screenheight()
        x = (screen_width // 2) - 190
        y = (screen_height // 2) - 80
        progress_win.geometry(f"+{x}+{y}")
        
        lbl = ctk.CTkLabel(
            progress_win,
            text=f"Downloading DeviceLink update to {latest_tag}...",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        lbl.pack(pady=(20, 10))
        
        progress_bar = ctk.CTkProgressBar(progress_win, width=320)
        progress_bar.set(0)
        progress_bar.pack(pady=5)
        
        progress_lbl = ctk.CTkLabel(
            progress_win,
            text="0%",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        progress_lbl.pack(pady=(0, 15))
        
        self.start_download_and_install(download_url, latest_tag, progress_win, progress_bar, progress_lbl)

    def start_download_and_install(self, download_url, version_str, progress_win, progress_bar, progress_lbl):
        def worker():
            try:
                target_path = None
                if getattr(sys, 'frozen', False):
                    current_exe = sys.executable
                    update_exe = os.path.join(os.path.dirname(current_exe), "devlinkupdate.exe")
                    if os.path.exists(update_exe):
                        try:
                            os.remove(update_exe)
                        except Exception:
                            pass
                    try:
                        os.rename(current_exe, update_exe)
                    except Exception:
                        pass
                    target_path = current_exe
                else:
                    target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DeviceLink_new.exe")

                req = urllib.request.Request(download_url, headers={'User-Agent': 'DeviceLink-Updater/1.0'})
                with urllib.request.urlopen(req, timeout=30.0) as response:
                    total_size = int(response.info().get('Content-Length', 0))
                    downloaded = 0
                    block_size = 1024 * 64
                    
                    with open(target_path, 'wb') as f:
                        while True:
                            buffer = response.read(block_size)
                            if not buffer:
                                break
                            f.write(buffer)
                            downloaded += len(buffer)
                            if total_size > 0:
                                percent = downloaded / total_size
                                self.after(0, lambda p=percent: [
                                    progress_bar.set(p), 
                                    progress_lbl.configure(text=f"{int(p*100)}% ({downloaded // 1024} KB / {total_size // 1024} KB)")
                                ])
                
                if getattr(sys, 'frozen', False):
                    self.after(0, progress_win.destroy)
                    self.after(0, lambda: self.prompt_update_success(target_path))
                else:
                    self.after(0, progress_win.destroy)
                    self.after(0, lambda: self.show_dev_mode_info(target_path))
                    
            except Exception as e:
                self.after(0, progress_win.destroy)
                self.after(0, lambda err=str(e): self.show_update_error(err))
                
        threading.Thread(target=worker, daemon=True).start()

    def prompt_update_success(self, current_exe):
        try:
            update_exe = os.path.join(os.path.dirname(current_exe), "devlinkupdate.exe")
            vbs_path = os.path.join(tempfile.gettempdir(), "devicelink_update.vbs")
            with open(vbs_path, "w") as f:
                f.write('WScript.Sleep 2000\n')
                f.write('Set objShell = CreateObject("WScript.Shell")\n')
                f.write('objShell.Run "explorer.exe """ & WScript.Arguments(0) & """", 0, False\n')
                f.write('WScript.Sleep 3000\n')
                f.write('Set objFSO = CreateObject("Scripting.FileSystemObject")\n')
                f.write('On Error Resume Next\n')
                f.write('objFSO.DeleteFile WScript.Arguments(1), True\n')
                f.write('objFSO.DeleteFile WScript.ScriptFullName, True\n')

            subprocess.Popen(["wscript.exe", vbs_path, current_exe, update_exe], creationflags=0x08000000)
        except Exception as e:
            print(f"[Updater] Failed to restart: {e}")
        
        if hasattr(self, 'tray_icon') and self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        os._exit(0)

    def show_dev_mode_info(self, dev_dest):
        from tkinter import messagebox
        messagebox.showinfo("Simulation Complete", f"Running in development mode (not frozen). The new binary was saved to:\n\n{dev_dest}")

    def show_update_error(self, err_msg):
        from tkinter import messagebox
        messagebox.showerror("Update Failed", f"An error occurred during the update:\n\n{err_msg}")

    def _build_android_tab(self):
        # Container frame
        container = ctk.CTkFrame(self.tab_android, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # ── LEFT PANEL: WALLPAPER MOCKUP ──
        wallpaper_panel = ctk.CTkFrame(
            container,
            fg_color="#0F172A",
            width=340,
            corner_radius=16,
            border_width=1,
            border_color="#1E293B"
        )
        wallpaper_panel.pack(side="left", fill="both", padx=(0, 10), pady=10)
        wallpaper_panel.pack_propagate(False)

        # Smartphone Mockup Frame
        phone_frame = ctk.CTkFrame(
            wallpaper_panel,
            fg_color="#1E293B",
            width=260,
            height=440,
            corner_radius=24
        )
        phone_frame.pack(anchor="center", pady=(40, 20))
        phone_frame.pack_propagate(False)

        # Screen inside the phone mockup — use gradient start color so no black shows
        screen_frame = ctk.CTkFrame(
            phone_frame,
            fg_color="#0d1b2e",
            width=244,
            height=420,
            corner_radius=18
        )
        screen_frame.place(relx=0.5, rely=0.5, anchor="center")
        screen_frame.pack_propagate(False)
        self._screen_frame = screen_frame  # store ref for color updates

        # Wallpaper Image Label inside the Screen
        self.wallpaper_label = ctk.CTkLabel(
            screen_frame,
            text="Waiting for wallpaper sync...",
            font=ctk.CTkFont(size=12),
            text_color="#64748B"
        )
        self.wallpaper_label.place(x=0, y=0, relwidth=1, relheight=1)

        # Transparent overlay container for shortcut app cards
        self.apps_grid_frame = ctk.CTkFrame(screen_frame, fg_color="transparent")
        self.apps_grid_frame.place(x=0, y=0, relwidth=1, relheight=1)

        # Load dynamic premium placeholder gradient as default wallpaper
        try:
            placeholder_img = self.generate_placeholder_wallpaper()
            self.ctk_placeholder_img = ctk.CTkImage(
                light_image=placeholder_img,
                dark_image=placeholder_img,
                size=(244, 420)
            )
            self.wallpaper_label.configure(image=self.ctk_placeholder_img, text="")
        except Exception as e:
            print(f"[GUI] Error generating placeholder wallpaper: {e}")

        # ── RIGHT PANEL: SYSTEM STATUS & DETAILS ──
        status_panel = ctk.CTkFrame(
            container,
            fg_color="#0F172A",
            corner_radius=16,
            border_width=1,
            border_color="#1E293B"
        )
        status_panel.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)

        # Battery Card (Top Right)
        self.card_battery = ctk.CTkFrame(status_panel, fg_color="#1E293B", height=80)
        self.card_battery.pack(fill="x", padx=20, pady=(15, 15))
        self.card_battery.pack_propagate(False)

        self.battery_icon_label = ctk.CTkLabel(
            self.card_battery, text="🔋", font=ctk.CTkFont(size=24)
        )
        self.battery_icon_label.pack(side="left", padx=(15, 10))

        self.battery_pct_label = ctk.CTkLabel(
            self.card_battery, text="--%", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC"
        )
        self.battery_pct_label.pack(side="left", padx=5)

        self.battery_state_label = ctk.CTkLabel(
            self.card_battery, text="Discharging", font=ctk.CTkFont(size=12), text_color="#94A3B8"
        )
        self.battery_state_label.pack(side="left", padx=15)

        self.battery_progress = ctk.CTkProgressBar(self.card_battery, height=8, width=150)
        self.battery_progress.pack(side="right", padx=15)
        self.battery_progress.set(0.0)

        # 4x1 Grid Section for DND, Airplane, Ringer, Vibrate
        self.grid_frame = ctk.CTkFrame(status_panel, fg_color="transparent")
        self.grid_frame.pack(fill="x", padx=20, pady=(0, 15))
        self.grid_frame.columnconfigure((0, 1, 2, 3), weight=1, uniform="grid")

        # 1. Ringer Card — clickable to cycle Normal → Silent → Vibrate
        self.card_ringer = ctk.CTkFrame(self.grid_frame, fg_color="#1E293B", height=85, cursor="hand2")
        self.card_ringer.grid(row=0, column=0, padx=5, sticky="nsew")
        self.card_ringer.pack_propagate(False)
        self.card_ringer.bind("<Button-1>", lambda e: self.toggle_ringer())
        self.lbl_ringer_icon = ctk.CTkLabel(self.card_ringer, text="🔊", font=ctk.CTkFont(size=22), cursor="hand2")
        self.lbl_ringer_icon.pack(pady=(12, 2))
        self.lbl_ringer_icon.bind("<Button-1>", lambda e: self.toggle_ringer())
        self.lbl_ringer_text = ctk.CTkLabel(self.card_ringer, text="Ringer: Normal", font=ctk.CTkFont(size=11), text_color="#10B981", cursor="hand2")
        self.lbl_ringer_text.pack()
        self.lbl_ringer_text.bind("<Button-1>", lambda e: self.toggle_ringer())

        # 2. Vibrate Card — clickable to toggle vibrate
        self.card_vibrate = ctk.CTkFrame(self.grid_frame, fg_color="#1E293B", height=85, cursor="hand2")
        self.card_vibrate.grid(row=0, column=1, padx=5, sticky="nsew")
        self.card_vibrate.pack_propagate(False)
        self.card_vibrate.bind("<Button-1>", lambda e: self.toggle_vibrate())
        self.lbl_vibrate_icon = ctk.CTkLabel(self.card_vibrate, text="📳", font=ctk.CTkFont(size=22), cursor="hand2")
        self.lbl_vibrate_icon.pack(pady=(12, 2))
        self.lbl_vibrate_icon.bind("<Button-1>", lambda e: self.toggle_vibrate())
        self.lbl_vibrate_text = ctk.CTkLabel(self.card_vibrate, text="Vibrate: Off", font=ctk.CTkFont(size=11), text_color="#94A3B8", cursor="hand2")
        self.lbl_vibrate_text.pack()
        self.lbl_vibrate_text.bind("<Button-1>", lambda e: self.toggle_vibrate())

        # 3. DND Card — clickable to toggle DND
        self.card_dnd = ctk.CTkFrame(self.grid_frame, fg_color="#1E293B", height=85, cursor="hand2")
        self.card_dnd.grid(row=0, column=2, padx=5, sticky="nsew")
        self.card_dnd.pack_propagate(False)
        self.card_dnd.bind("<Button-1>", lambda e: self.toggle_dnd())
        self.lbl_dnd_icon = ctk.CTkLabel(self.card_dnd, text="🌙", font=ctk.CTkFont(size=22), cursor="hand2")
        self.lbl_dnd_icon.pack(pady=(12, 2))
        self.lbl_dnd_icon.bind("<Button-1>", lambda e: self.toggle_dnd())
        self.lbl_dnd_text = ctk.CTkLabel(self.card_dnd, text="DND: Off", font=ctk.CTkFont(size=11), text_color="#94A3B8", cursor="hand2")
        self.lbl_dnd_text.pack()
        self.lbl_dnd_text.bind("<Button-1>", lambda e: self.toggle_dnd())

        # 4. Airplane Card — clickable to toggle airplane mode
        self.card_airplane = ctk.CTkFrame(self.grid_frame, fg_color="#1E293B", height=85, cursor="hand2")
        self.card_airplane.grid(row=0, column=3, padx=5, sticky="nsew")
        self.card_airplane.pack_propagate(False)
        self.card_airplane.bind("<Button-1>", lambda e: self.toggle_airplane())
        self.lbl_airplane_icon = ctk.CTkLabel(self.card_airplane, text="✈️", font=ctk.CTkFont(size=22), cursor="hand2")
        self.lbl_airplane_icon.pack(pady=(12, 2))
        self.lbl_airplane_icon.bind("<Button-1>", lambda e: self.toggle_airplane())
        self.lbl_airplane_text = ctk.CTkLabel(self.card_airplane, text="Airplane: Off", font=ctk.CTkFont(size=11), text_color="#94A3B8", cursor="hand2")
        self.lbl_airplane_text.pack()
        self.lbl_airplane_text.bind("<Button-1>", lambda e: self.toggle_airplane())

        # Notifications list title
        ctk.CTkLabel(
            status_panel,
            text="Notifications",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F8FAFC"
        ).pack(anchor="w", padx=20, pady=(5, 5))

        # Scrollable Notifications list
        self.notif_container = ctk.CTkScrollableFrame(status_panel, height=210)
        self.notif_container.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Default text
        self.notif_status_lbl = ctk.CTkLabel(
            self.notif_container,
            text="No active notifications",
            text_color="gray"
        )
        self.notif_status_lbl.pack(pady=30)

        # Bottom row for Messages button
        self.bottom_row = ctk.CTkFrame(status_panel, fg_color="transparent")
        self.bottom_row.pack(fill="x", padx=20, pady=(5, 15))

        self.open_messages_btn = ctk.CTkButton(
            self.bottom_row,
            text="💬 Open Phone Messages (SMS)",
            height=36,
            command=self.open_messages_window
        )
        self.open_messages_btn.pack(fill="x")

    def generate_placeholder_wallpaper(self):
        img = Image.new("RGBA", (244, 420), "#0F172A")
        # simple blue/purple dark gradient
        for y in range(420):
            r = int(15 + (45 - 15) * (y / 420))
            g = int(23 + (15 - 23) * (y / 420))
            b = int(42 + (70 - 42) * (y / 420))
            for x in range(244):
                img.putpixel((x, y), (r, g, b, 255))
        return img

    def resize_cover(self, pil_img, target_width, target_height):
        orig_w, orig_h = pil_img.size
        target_ratio = target_width / target_height
        orig_ratio = orig_w / orig_h
        
        if orig_ratio > target_ratio:
            new_h = target_height
            new_w = int(orig_w * (target_height / orig_h))
            resample_filter = getattr(Image, 'Resampling', None)
            if resample_filter:
                resample = resample_filter.LANCZOS
            else:
                resample = Image.ANTIALIAS
            scaled = pil_img.resize((new_w, new_h), resample)
            left = (new_w - target_width) // 2
            return scaled.crop((left, 0, left + target_width, target_height))
        else:
            new_w = target_width
            new_h = int(orig_h * (target_width / orig_w))
            resample_filter = getattr(Image, 'Resampling', None)
            if resample_filter:
                resample = resample_filter.LANCZOS
            else:
                resample = Image.ANTIALIAS
            scaled = pil_img.resize((new_w, new_h), resample)
            top = (new_h - target_height) // 2
            return scaled.crop((0, top, target_width, top + target_height))

    def hex_to_rgb(self, hex_str):
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

    def generate_gradient_image(self, rgb1, rgb2, width, height):
        # Create a 1x256 image with a vertical gradient, then scale it
        gradient = Image.new("RGB", (1, 256))
        for y in range(256):
            factor = y / 255.0
            r = int(rgb1[0] * (1 - factor) + rgb2[0] * factor)
            g = int(rgb1[1] * (1 - factor) + rgb2[1] * factor)
            b = int(rgb1[2] * (1 - factor) + rgb2[2] * factor)
            gradient.putpixel((0, y), (r, g, b))
        return gradient.resize((width, height), Image.Resampling.LANCZOS)

    def on_tab_changed(self):
        self.update_telemetry_sync_state()
        if self.tabview.get() == "AI Agent":
            if hasattr(self, "agent_canvas") and self.agent_canvas:
                self.agent_canvas.set_state("idle")
                if self.agent_canvas.response_box:
                    self.agent_canvas.response_box.place_forget()

    def update_telemetry_sync_state(self):
        from nexuslink.server.ws_server import get_active_peers, get_cloud_relay_active
        from nexuslink.server.udp_server import get_active_udp_peer
        is_connected = bool(get_active_peers() or get_active_udp_peer() or get_cloud_relay_active())
        
        is_active = (
            is_connected
            and self.tabview.get() == "Android"
            and self.winfo_viewable()
            and self.state() != "iconic"
        )
        current_sync = getattr(self, "telemetry_sync_active", False)
        if is_active != current_sync:
            self.telemetry_sync_active = is_active
            action = "start" if is_active else "stop"
            try:
                from nexuslink.server.ws_server import send_message_to_all_peers_sync
                send_message_to_all_peers_sync("telemetry_control", {"action": action})
                print(f"[GUI] Sent telemetry_control: {action}")
            except Exception as e:
                print(f"[GUI] Error sending telemetry_control: {e}")

    def open_messages_window(self):
        if hasattr(self, "messages_win") and self.messages_win and self.messages_win.winfo_exists():
            self.messages_win.lift()
            self.messages_win.focus()
            return
            
        self.messages_win = ctk.CTkToplevel(self)
        self.messages_win.title("Phone Messages (SMS)")
        self.messages_win.geometry("600x480")
        self.messages_win.resizable(False, False)
        self.messages_win.attributes("-topmost", True)
        self.messages_win.transient(self)
        
        # Header
        ctk.CTkLabel(
            self.messages_win,
            text="Phone Messages",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=20, pady=(20, 5))
        
        # Scrollable container for messages
        self.sms_container = ctk.CTkScrollableFrame(self.messages_win)
        self.sms_container.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        # Label showing state
        self.sms_status_lbl = ctk.CTkLabel(
            self.sms_container,
            text="Loading messages from Android...",
            text_color="gray"
        )
        self.sms_status_lbl.pack(pady=40)
        
        # Bind window closing event
        self.messages_win.protocol("WM_DELETE_WINDOW", self.close_messages_window)
        
        # Tell Android to start SMS sync
        try:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            send_message_to_all_peers_sync("start_sms_sync", {})
            print("[GUI] Sent start_sms_sync")
        except Exception as e:
            print(f"[GUI] Error starting SMS sync: {e}")

    def close_messages_window(self):
        try:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            send_message_to_all_peers_sync("stop_sms_sync", {})
            print("[GUI] Sent stop_sms_sync")
        except Exception as e:
            print(f"[GUI] Error stopping SMS sync: {e}")
            
        if hasattr(self, "messages_win") and self.messages_win:
            self.messages_win.destroy()
            self.messages_win = None

    def dismiss_notification(self, notif_id):
        try:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            send_message_to_all_peers_sync("dismiss_notification", {"id": notif_id})
            print(f"[GUI] Requested to dismiss notification: {notif_id}")
        except Exception as e:
            print(f"[GUI] Error dismissing notification: {e}")

    def request_open_notification_settings(self):
        try:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            send_message_to_all_peers_sync("android_action", {"action": "open_notification_settings"})
            print("[GUI] Sent open_notification_settings action to Android")
        except Exception as e:
            print(f"[GUI] Error sending open_notification_settings: {e}")

    def handle_sync_notifications(self, payload):
        if not hasattr(self, "notif_container") or not self.notif_container or not self.notif_container.winfo_exists():
            return

        # Clear previous items
        for child in self.notif_container.winfo_children():
            child.destroy()

        error = payload.get("error")
        if error in ["permission_denied", "listener_not_bound"]:
            frame = ctk.CTkFrame(self.notif_container, fg_color="transparent")
            frame.pack(pady=30)
            
            if error == "permission_denied":
                msg_text = "Notification Access Restricted.\nPlease enable Notification Access in Android settings.\n\n(If blocked, go to Phone Settings ➔ Apps ➔ DeviceLink ➔ tap ⋮ in top right ➔ 'Allow restricted settings')"
            else:
                msg_text = "Notification Listener Unbound.\nPlease toggle Notification Access OFF and ON again in Phone Settings to reactivate syncing."

            ctk.CTkLabel(
                frame,
                text=msg_text,
                text_color="#EF4444",
                font=ctk.CTkFont(size=11, weight="normal"),
                wraplength=320
            ).pack(pady=(0, 10))
            
            ctk.CTkButton(
                frame,
                text="Open Phone Settings",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#EF4444",
                hover_color="#DC2626",
                height=28,
                command=self.request_open_notification_settings
            ).pack()
            return

        notifications = payload.get("notifications", [])
        if not notifications:
            ctk.CTkLabel(
                self.notif_container,
                text="No active notifications",
                text_color="gray"
            ).pack(pady=30)
            return

        # Render each notification
        for notif in notifications:
            notif_id = notif.get("id", "")
            pkg = notif.get("package", "System")
            title = notif.get("title", "")
            text = notif.get("text", "")
            is_clearable = notif.get("is_clearable", True)

            app_name = pkg.split(".")[-1].capitalize()

            card = ctk.CTkFrame(self.notif_container, fg_color="#1E293B", corner_radius=8)
            card.pack(fill="x", pady=3, padx=5)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=(6, 2))

            ctk.CTkLabel(
                header,
                text=app_name,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#38BDF8"
            ).pack(side="left")

            if is_clearable:
                btn_dismiss = ctk.CTkButton(
                    header,
                    text="✕",
                    width=18,
                    height=18,
                    fg_color="transparent",
                    hover_color="#334155",
                    text_color="gray",
                    font=ctk.CTkFont(size=10),
                    command=lambda nid=notif_id: self.dismiss_notification(nid)
                )
                btn_dismiss.pack(side="right")

            content_frame = ctk.CTkFrame(card, fg_color="transparent")
            content_frame.pack(fill="x", padx=10, pady=(2, 6))

            if title:
                ctk.CTkLabel(
                    content_frame,
                    text=title,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#F8FAFC",
                    anchor="w",
                    justify="left",
                    wraplength=350
                ).pack(fill="x")

            if text:
                ctk.CTkLabel(
                    content_frame,
                    text=text,
                    font=ctk.CTkFont(size=10),
                    text_color="#94A3B8",
                    anchor="w",
                    justify="left",
                    wraplength=350
                ).pack(fill="x")

    def handle_sync_sms(self, payload):
        if not hasattr(self, "sms_container") or not self.sms_container or not self.sms_container.winfo_exists():
            return
            
        for child in self.sms_container.winfo_children():
            child.destroy()
            
        error = payload.get("error")
        if error == "permission_denied":
            ctk.CTkLabel(
                self.sms_container,
                text="Permission Restricted.\nPlease grant SMS permission on the Android app.",
                text_color="#EF4444",
                font=ctk.CTkFont(size=13, weight="bold")
            ).pack(pady=40)
            return
            
        messages = payload.get("messages", [])
        if not messages:
            ctk.CTkLabel(
                self.sms_container,
                text="No SMS messages found.",
                text_color="gray"
            ).pack(pady=40)
            return
            
        import datetime
        for msg in messages:
            sender = msg.get("sender", "Unknown")
            body = msg.get("body", "")
            date_ms = msg.get("date", 0)
            is_read = msg.get("read", True)
            
            time_str = ""
            if date_ms > 0:
                try:
                    dt = datetime.datetime.fromtimestamp(date_ms / 1000.0)
                    time_str = dt.strftime("%b %d, %H:%M")
                except Exception:
                    pass
                    
            card = ctk.CTkFrame(
                self.sms_container,
                fg_color="#1E293B" if is_read else "#0F172A",
                border_width=0 if is_read else 1,
                border_color="#3B82F6",
                corner_radius=8
            )
            card.pack(fill="x", pady=4, padx=5)
            
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=(6, 2))
            
            ctk.CTkLabel(
                header,
                text=sender,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#38BDF8" if not is_read else "#F8FAFC"
            ).pack(side="left")
            
            ctk.CTkLabel(
                header,
                text=time_str,
                font=ctk.CTkFont(size=10),
                text_color="gray"
            ).pack(side="right")
            
            body_lbl = ctk.CTkLabel(
                card,
                text=body,
                font=ctk.CTkFont(size=11),
                text_color="#CBD5E1",
                justify="left",
                wraplength=520,
                anchor="w"
            )
            body_lbl.pack(fill="x", padx=10, pady=(2, 8))

    def handle_sync_phone_status(self, payload):
        wallpaper_b64 = payload.get("wallpaper", "")
        primary_color = payload.get("primary_color", "")
        secondary_color = payload.get("secondary_color", "")
        
        old_primary = getattr(self, "wallpaper_primary_color", "")
        old_secondary = getattr(self, "wallpaper_secondary_color", "")
        color_changed = (primary_color != old_primary or 
                         secondary_color != old_secondary or 
                         wallpaper_b64 != "")
        
        self.wallpaper_primary_color = primary_color
        self.wallpaper_secondary_color = secondary_color
        
        if wallpaper_b64:
            try:
                import base64
                from io import BytesIO
                
                img_data = base64.b64decode(wallpaper_b64)
                pil_img = Image.open(BytesIO(img_data))
                cropped_img = self.resize_cover(pil_img, 244, 420)
                ctk_img = ctk.CTkImage(light_image=cropped_img, dark_image=cropped_img, size=(244, 420))
                self.wallpaper_label.configure(image=ctk_img, text="")
                self.wallpaper_label.image = ctk_img
            except Exception as e:
                print(f"[GUI] Error displaying wallpaper: {e}")
        elif primary_color:
            try:
                p_rgb = self.hex_to_rgb(primary_color)
                if secondary_color:
                    s_rgb = self.hex_to_rgb(secondary_color)
                else:
                    s_rgb = tuple(max(0, int(c * 0.35)) for c in p_rgb)
                
                grad_img = self.generate_gradient_image(p_rgb, s_rgb, 244, 420)
                ctk_img = ctk.CTkImage(light_image=grad_img, dark_image=grad_img, size=(244, 420))
                self.wallpaper_label.configure(image=ctk_img, text="")
                self.wallpaper_label.image = ctk_img
            except Exception as e:
                print(f"[GUI] Error displaying gradient: {e}")

            # Dynamically match app's theme to dominant colors
            try:
                self.open_messages_btn.configure(fg_color=primary_color)
                if secondary_color:
                    self.open_messages_btn.configure(hover_color=secondary_color)
                
                if hasattr(self.tabview, "_segmented_button") and self.tabview._segmented_button:
                    self.tabview._segmented_button.configure(
                        selected_color=primary_color,
                        selected_hover_color=secondary_color if secondary_color else primary_color
                    )
            except Exception as e:
                print(f"[GUI] Error applying dynamic theme: {e}")
        else:
            self.wallpaper_primary_color = ""
            self.wallpaper_secondary_color = ""
            try:
                self.wallpaper_label.configure(image=self.ctk_placeholder_img, text="Live status synced\n(Wallpaper access restricted)", text_color="#94A3B8")
            except Exception:
                pass

            # Reset colors to default customtkinter colors on disconnection or if colors restricted
            try:
                self.open_messages_btn.configure(fg_color="#1f538d", hover_color="#14375e")
                if hasattr(self.tabview, "_segmented_button") and self.tabview._segmented_button:
                    self.tabview._segmented_button.configure(
                        selected_color="#1f538d",
                        selected_hover_color="#14375e"
                    )
            except Exception:
                pass

        if color_changed:
            try:
                self.update_deck_apps_display()
            except Exception as e:
                print(f"[GUI] Error updating deck apps display on phone status sync: {e}")

        battery_level = payload.get("battery_level", 100)
        is_charging = payload.get("is_charging", False)
        self.battery_pct_label.configure(text=f"{battery_level}%")
        self.battery_progress.set(battery_level / 100.0)
        
        if is_charging:
            self.battery_state_label.configure(text="Charging", text_color="#06B6D4")
            self.battery_progress.configure(progress_color="#06B6D4")
            self.battery_icon_label.configure(text="🔌🔋")
        else:
            self.battery_state_label.configure(text="Discharging", text_color="#94A3B8")
            self.battery_icon_label.configure(text="🔋")
            if battery_level <= 20:
                self.battery_progress.configure(progress_color="#EF4444")
            else:
                if primary_color:
                    self.battery_progress.configure(progress_color=primary_color)
                else:
                    self.battery_progress.configure(progress_color="#10B981")

        ringer_mode = payload.get("ringer_mode", "normal")
        if ringer_mode == "normal":
            self.lbl_ringer_icon.configure(text="🔊")
            self.lbl_ringer_text.configure(text="Ringer: Normal", text_color="#10B981")
            self.lbl_vibrate_icon.configure(text="📳", text_color="#F8FAFC")
            self.lbl_vibrate_text.configure(text="Vibrate: Off", text_color="#94A3B8")
            self.card_vibrate.configure(border_width=0)
        elif ringer_mode == "vibrate":
            self.lbl_ringer_icon.configure(text="🔇")
            self.lbl_ringer_text.configure(text="Ringer: Silent", text_color="#EF4444")
            self.lbl_vibrate_icon.configure(text="📳", text_color="#F59E0B")
            self.lbl_vibrate_text.configure(text="Vibrate: On", text_color="#F59E0B")
            self.card_vibrate.configure(border_color="#F59E0B", border_width=1)
        elif ringer_mode == "silent":
            self.lbl_ringer_icon.configure(text="🔇")
            self.lbl_ringer_text.configure(text="Ringer: Silent", text_color="#EF4444")
            self.lbl_vibrate_icon.configure(text="📳", text_color="#F8FAFC")
            self.lbl_vibrate_text.configure(text="Vibrate: Off", text_color="#94A3B8")
            self.card_vibrate.configure(border_width=0)

        dnd_enabled = payload.get("dnd_enabled", False)
        if dnd_enabled:
            self.lbl_dnd_icon.configure(text="🌙", text_color="#A855F7")
            self.lbl_dnd_text.configure(text="DND: On", text_color="#A855F7")
            self.card_dnd.configure(border_color="#A855F7", border_width=1)
        else:
            self.lbl_dnd_icon.configure(text="🌙", text_color="#F8FAFC")
            self.lbl_dnd_text.configure(text="DND: Off", text_color="#94A3B8")
            self.card_dnd.configure(border_width=0)

        airplane_mode = payload.get("airplane_mode", False)
        if airplane_mode:
            self.lbl_airplane_icon.configure(text="✈️", text_color="#3B82F6")
            self.lbl_airplane_text.configure(text="Airplane: On", text_color="#3B82F6")
            self.card_airplane.configure(border_color="#3B82F6", border_width=1)
        else:
            self.lbl_airplane_icon.configure(text="✈️", text_color="#F8FAFC")
            self.lbl_airplane_text.configure(text="Airplane: Off", text_color="#94A3B8")
            self.card_airplane.configure(border_width=0)

    def handle_sync_desktop_deck(self, payload):
        raw_apps = payload.get("apps", [])
        # Normalize: ensure every item is a dict (guard against JSON arrays of non-dicts)
        apps = [a for a in raw_apps if isinstance(a, dict)]
        print(f"[GUI] handle_sync_desktop_deck: received {len(raw_apps)} apps, {len(apps)} valid dicts")
        for i, a in enumerate(apps):
            print(f"[GUI]   app[{i}]: label={a.get('label','?')!r}, pkg={a.get('package','?')!r}, icon_len={len(a.get('icon',''))}")
        self.desktop_deck_apps = apps
        self.update_deck_apps_display()

    def update_deck_apps_display(self):
        # 1. Clear existing tracked widgets
        for widget in self.deck_app_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self.deck_app_widgets.clear()
            
        # 2. Reconfigure columns and rows on the transparent overlay frame
        try:
            parent_widget = self.apps_grid_frame
            parent_widget.grid_columnconfigure(0, weight=1)
            parent_widget.grid_columnconfigure(1, weight=1)
            for i in range(5):
                parent_widget.grid_rowconfigure(i, weight=1)
        except Exception as e:
            print(f"[GUI] update_deck_apps_display: error configuring parent_widget grid: {e}")
            return
            
        def blend_colors(color_hex, target_hex, alpha):
            if not color_hex or not color_hex.startswith("#"):
                color_hex = "#1a2a4a"
            if not target_hex or not target_hex.startswith("#"):
                target_hex = "#000000"
            try:
                c1 = color_hex.strip().lstrip('#')
                c2 = target_hex.strip().lstrip('#')
                if len(c1) == 3:
                    c1 = "".join(x*2 for x in c1)
                if len(c2) == 3:
                    c2 = "".join(x*2 for x in c2)
                r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
                r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
                r = int(r1 * (1.0 - alpha) + r2 * alpha)
                g = int(g1 * (1.0 - alpha) + g2 * alpha)
                b = int(b1 * (1.0 - alpha) + b2 * alpha)
                return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"
            except Exception:
                return target_hex

        # 3. Determine colors
        bg_hex = self.wallpaper_primary_color if self.wallpaper_primary_color else "#1a2a4a"
        card_fg = blend_colors(bg_hex, "#000000", 0.40)      # Translucent dark overlay
        card_border = blend_colors(bg_hex, "#FFFFFF", 0.15)  # Glassmorphic border
        hover_color = blend_colors(bg_hex, "#FFFFFF", 0.25)  # Lighter hover highlight
        
        def get_app_abbreviation(name: str) -> str:
            if not name:
                return "??"
            parts = name.split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[1][0]).upper()
            return name[:2].upper()
            
        # 4. Display up to 10 apps
        apps_to_show = self.desktop_deck_apps[:10]
        for idx, app in enumerate(apps_to_show):
            name = app.get("label") or app.get("name") or "Unknown"
            pkg = app.get("package", "")
            icon_b64 = app.get("icon", "")
            
            r = idx // 2
            c = idx % 2
            
            # Create a rounded container card for the icon + text to make it unified and prevent ugly background box issues
            card = ctk.CTkFrame(
                parent_widget,
                fg_color=card_fg,
                border_color=card_border,
                border_width=1,
                corner_radius=12
            )
            card.grid(row=r, column=c, padx=8, pady=5, sticky="nsew")
            self.deck_app_widgets.append(card)
            
            icon_image = None
            if icon_b64:
                try:
                    import base64
                    from io import BytesIO
                    
                    icon_data = base64.b64decode(icon_b64)
                    pil_img = Image.open(BytesIO(icon_data))
                    resample_filter = getattr(Image, 'Resampling', None)
                    resample = resample_filter.LANCZOS if resample_filter else Image.ANTIALIAS
                    resized_img = pil_img.resize((36, 36), resample)
                    icon_image = ctk.CTkImage(light_image=resized_img, dark_image=resized_img, size=(36, 36))
                except Exception as e:
                    print(f"[GUI] Error decoding app icon: {e}")
            
            if icon_image:
                btn = ctk.CTkButton(
                    card,
                    image=icon_image,
                    text="",
                    width=38,
                    height=38,
                    corner_radius=8,
                    fg_color="transparent",
                    hover_color=hover_color,
                    command=lambda p=pkg: self.launch_deck_app(p)
                )
            else:
                abbrev = get_app_abbreviation(name)
                btn = ctk.CTkButton(
                    card,
                    text=abbrev,
                    width=38,
                    height=38,
                    corner_radius=8,
                    fg_color=bg_hex,
                    hover_color=hover_color,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#FFFFFF",
                    command=lambda p=pkg: self.launch_deck_app(p)
                )
            btn.pack(pady=(8, 2), anchor="center")
            
            display_name = name if len(name) <= 12 else name[:10] + ".."
            lbl = ctk.CTkLabel(
                card,
                text=display_name,
                font=ctk.CTkFont(size=10),
                text_color="#CBD5E1",
                fg_color="transparent"
            )
            lbl.pack(pady=(0, 8), anchor="center")

    def launch_deck_app(self, package_name):
        if package_name:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            send_message_to_all_peers_sync("android_action", {"action": "launch_app", "package": package_name})

    def _send_android_action(self, action: str, **kwargs):
        """Helper to send any android_action to the phone."""
        try:
            from nexuslink.server.ws_server import send_message_to_all_peers_sync
            payload = {"action": action, **kwargs}
            send_message_to_all_peers_sync("android_action", payload)
        except Exception as e:
            print(f"[GUI] Error sending android_action '{action}': {e}")

    def toggle_ringer(self):
        current = self.lbl_ringer_text.cget("text")
        if "Normal" in current:
            next_mode = "silent"
            label, icon, color = "Ringer: Silent", "🔇", "#EF4444"
        else:
            next_mode = "normal"
            label, icon, color = "Ringer: Normal", "🔊", "#10B981"
        self.lbl_ringer_text.configure(text=label, text_color=color)
        self.lbl_ringer_icon.configure(text=icon)
        self._send_android_action("set_ringer_mode", mode=next_mode)

    # ── Vibrate toggle ──────────────────────────────────────────────────────
    def toggle_vibrate(self):
        current = self.lbl_vibrate_text.cget("text")
        if "Off" in current:
            self.lbl_vibrate_text.configure(text="Vibrate: On", text_color="#F59E0B")
            self.lbl_vibrate_icon.configure(text="📳", text_color="#F59E0B")
            self.card_vibrate.configure(border_color="#F59E0B", border_width=1)
            self._send_android_action("set_vibrate", state=True)
        else:
            self.lbl_vibrate_text.configure(text="Vibrate: Off", text_color="#94A3B8")
            self.lbl_vibrate_icon.configure(text="📳", text_color="#F8FAFC")
            self.card_vibrate.configure(border_width=0)
            self._send_android_action("set_vibrate", state=False)

    # ── DND toggle ──────────────────────────────────────────────────────────
    def toggle_dnd(self):
        current = self.lbl_dnd_text.cget("text")
        if "Off" in current:
            self.lbl_dnd_text.configure(text="DND: On", text_color="#A855F7")
            self.lbl_dnd_icon.configure(text="🌙")
            self.card_dnd.configure(border_color="#A855F7", border_width=1)
            self._send_android_action("set_dnd", state=True)
        else:
            self.lbl_dnd_text.configure(text="DND: Off", text_color="#94A3B8")
            self.card_dnd.configure(border_width=0)
            self._send_android_action("set_dnd", state=False)

    # ── Airplane toggle ─────────────────────────────────────────────────────
    def toggle_airplane(self):
        current = self.lbl_airplane_text.cget("text")
        if "Off" in current:
            self.lbl_airplane_text.configure(text="Airplane: On", text_color="#38BDF8")
            self.card_airplane.configure(border_color="#38BDF8", border_width=1)
            self._send_android_action("set_airplane_mode", state=True)
        else:
            self.lbl_airplane_text.configure(text="Airplane: Off", text_color="#94A3B8")
            self.card_airplane.configure(border_width=0)
            self._send_android_action("set_airplane_mode", state=False)


if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
