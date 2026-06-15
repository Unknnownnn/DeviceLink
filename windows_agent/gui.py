import sys
import queue
import logging
import socket

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

VERSION = "1.4.0"
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


class DeviceLinkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DeviceLink Dashboard")
        self.geometry("1050x650")
        self.resizable(False, False)
        self.settings = SettingsManager()
        self.check_single_instance()

        # Clean up old exe backups if they exist (fallback)
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
        self.call_overlay_window = None

        self.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.log_history = []
        self.logs_window = None
        self.log_textbox = None
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)
        self.tab_status = self.tabview.add("Status")
        self.tab_rules = self.tabview.add("Mobile Deck Shortcuts")
        self.tab_agent_test = self.tabview.add("AI Agent")
        self.tab_calls = self.tabview.add("Phone Calls")
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
        self.check_logs_loop()
        self.backend_thread = threading.Thread(target=self.start_backend, daemon=True)
        self.backend_thread.start()
        self.setup_tray()
        self.update_connection_status_loop()

    def _build_status_tab(self):
        status_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        status_frame.pack(fill="x", padx=10, pady=(20, 10))
        
        self.status_title = ctk.CTkLabel(
            status_frame, 
            text="DeviceLink Server Active", 
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.status_title.pack(anchor="w")

        self.status_info = ctk.CTkLabel(
            status_frame, 
            text="Port: 47200. Open the Android app to connect.", 
            text_color="gray",
            font=ctk.CTkFont(size=12)
        )
        self.status_info.pack(anchor="w", pady=(2, 10))

        self.conn_status_frame = ctk.CTkFrame(status_frame, fg_color="#1E293B", height=32, corner_radius=6)
        self.conn_status_frame.pack(anchor="w", pady=(0, 20))
        
        self.status_dot = ctk.CTkLabel(
            self.conn_status_frame, 
            text="●", 
            text_color="#F59E0B", 
            font=ctk.CTkFont(size=14)
        )
        self.status_dot.pack(side="left", padx=(12, 6))
        
        self.status_text = ctk.CTkLabel(
            self.conn_status_frame, 
            text="Waiting for Android connection...", 
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#CBD5E1"
        )
        self.status_text.pack(side="left", padx=(0, 12))

        button_row = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        button_row.pack(fill="x", padx=10, pady=10)

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

        # File Transfer Progress Bar
        self.progress_frame = ctk.CTkFrame(self.tab_status, fg_color="transparent")
        # Hidden by default

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
                    
                    self._update_progress_from_thread(filename, bytes_sent, file_size)
                    
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

    def update_connection_status_loop(self):
        try:
            from nexuslink.server.ws_server import get_active_peers, get_cloud_relay_active
            from nexuslink.server.udp_server import get_active_udp_peer
            peers = get_active_peers()
            udp_peer = get_active_udp_peer()
            if peers:
                peer_str = ", ".join(f"{p[0]}:{p[1]}" for p in peers)
                self.status_dot.configure(text_color="#10B981") # Green
                self.status_text.configure(text=f"Connected to {peer_str}")
                self.set_phone_tab_state("normal")
                self.send_file_btn.configure(state="normal")
            elif udp_peer:
                self.status_dot.configure(text_color="#10B981") # Green
                self.status_text.configure(text=f"Connected via STUN UDP: {udp_peer[0]}:{udp_peer[1]}")
                self.set_phone_tab_state("normal")
                self.send_file_btn.configure(state="normal")
            else:
                self.send_file_btn.configure(state="disabled")
                if get_cloud_relay_active():
                    self.status_dot.configure(text_color="#06B6D4") # Cyan
                    self.status_text.configure(text="Connected via Cloud Relay")
                    self.set_phone_tab_state("disabled")
                else:
                    self.status_dot.configure(text_color="#F59E0B") # Yellow/Orange
                    self.status_text.configure(text="Waiting for Android connection...")
                    self.set_phone_tab_state("disabled")
        except Exception:
            pass

        self.after(3000, self.update_connection_status_loop)

    def handle_cloud_relay_disconnect(self):
        self.status_dot.configure(text_color="#F59E0B")
        self.status_text.configure(text="Waiting for Android connection...")
        self.set_phone_tab_state("disabled")
        self.send_file_btn.configure(state="disabled")

    def set_phone_tab_state(self, state):
        try:
            if state == "disabled":
                if self.tabview.get() == "Phone Calls":
                    self.tabview.set("Status")
                self.tabview._segmented_button._buttons_dict["Phone Calls"].configure(state="disabled")
            else:
                self.tabview._segmented_button._buttons_dict["Phone Calls"].configure(state="normal")
        except Exception:
            pass

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

        self.refresh_rules_ui()

    def refresh_rules_ui(self):
        # 1. Clear previous content
        for widget in self.shortcuts_col_frame.winfo_children():
            widget.destroy()

        # ── RIGHT COLUMN: Mobile Client Shortcuts ──────────────────────
        ctk.CTkLabel(
            self.shortcuts_col_frame, 
            text="Mobile Deck Shortcuts", 
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Add Shortcut Form Container (pack bottom first!)
        sc_add_frame = ctk.CTkFrame(self.shortcuts_col_frame, fg_color="transparent")
        sc_add_frame.pack(fill="x", side="bottom", padx=15, pady=(5, 15))

        self.sc_name_entry = ctk.CTkEntry(sc_add_frame, placeholder_text="Shortcut Label")
        self.sc_name_entry.pack(fill="x", pady=2)

        sc_target_row = ctk.CTkFrame(sc_add_frame, fg_color="transparent")
        sc_target_row.pack(fill="x", pady=2)
        self.sc_target_entry = ctk.CTkEntry(sc_target_row, placeholder_text="Target Path/Steam ID/URL")
        self.sc_target_entry.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.sc_browse_btn = ctk.CTkButton(
            sc_target_row, text="Browse", width=60, 
            command=lambda: self.browse_exe(self.sc_target_entry)
        )
        self.sc_browse_btn.pack(side="left")

        # Type Row with option menu
        sc_type_row = ctk.CTkFrame(sc_add_frame, fg_color="transparent")
        sc_type_row.pack(fill="x", pady=2)
        ctk.CTkLabel(sc_type_row, text="Type:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        self.sc_type_var = ctk.StringVar(value="app")
        
        def on_type_change(val):
            if val == "app":
                self.sc_browse_btn.configure(state="normal")
            else:
                self.sc_browse_btn.configure(state="disabled")

        self.sc_type_menu = ctk.CTkOptionMenu(
            sc_type_row, values=["app", "steam", "url"], 
            variable=self.sc_type_var, command=on_type_change, width=80
        )
        self.sc_type_menu.pack(side="left", padx=5)

        ctk.CTkButton(
            sc_add_frame, text="Add Deck Shortcut", 
            command=self.add_shortcut
        ).pack(fill="x", pady=(5, 0))

        # Scrollable list for shortcuts (pack to expand)
        shortcuts_list_frame = ctk.CTkScrollableFrame(self.shortcuts_col_frame, fg_color="transparent")
        shortcuts_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        shortcuts = self.settings.get_deck_shortcuts()
        for s in shortcuts:
            row = ctk.CTkFrame(shortcuts_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            
            # Pack buttons FIRST on the right to keep them fixed in place
            # Remove button
            ctk.CTkButton(
                row, text="Remove", width=55, height=22, fg_color="#E74C3C", hover_color="#C0392B", 
                command=lambda sid=s['id']: self.remove_shortcut(sid)
            ).pack(side="right", padx=2)
            
            # Edit button
            ctk.CTkButton(
                row, text="Edit", width=45, height=22, fg_color="#3498DB", hover_color="#2980B9", 
                command=lambda item=s: self.edit_shortcut_window(item)
            ).pack(side="right", padx=2)
            
            # Pack label on the left
            display_label = f"{s['label']} [{s['type']}]"
            ctk.CTkLabel(row, text=display_label, font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left", padx=5, fill="x", expand=True)

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

    def show_window(self):
        self.after(0, self.deiconify)
        self.after(50, lambda: self.attributes("-topmost", True))
        self.after(100, lambda: self.attributes("-topmost", False))
        self.after(150, self.focus_force)

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

        # Title
        ctk.CTkLabel(
            test_frame, 
            text="Interactive AI Agent Sandbox", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 10))

        # Instructions
        ctk.CTkLabel(
            test_frame, 
            text="Type an NLP command below to test how the agent resolves, searches, or launches it on your PC.", 
            text_color="gray",
            font=ctk.CTkFont(size=12)
        ).pack(anchor="w", pady=(0, 15))

        # Input Row
        input_row = ctk.CTkFrame(test_frame, fg_color="transparent")
        input_row.pack(fill="x", pady=(0, 15))

        self.prompt_entry = ctk.CTkEntry(
            input_row, 
            placeholder_text="e.g., launch steam, open youtube, close notepad...",
            height=35
        )
        self.prompt_entry.pack(side="left", expand=True, fill="x", padx=(0, 10))
        
        # Bind enter key
        self.prompt_entry.bind("<Return>", lambda event: self.send_test_prompt())

        self.send_prompt_btn = ctk.CTkButton(
            input_row, 
            text="Run Command", 
            width=120, 
            height=35,
            command=self.send_test_prompt
        )
        self.send_prompt_btn.pack(side="right")

        # Terminal Log Container
        ctk.CTkLabel(
            test_frame, 
            text="Execution Log & Response:", 
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        self.test_console = ctk.CTkTextbox(
            test_frame, 
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0A0915",
            text_color="#A5F3FC",  # Nice cyan text for sandbox
            wrap="word"
        )
        self.test_console.pack(fill="both", expand=True)
        self.test_console.configure(state="disabled")

    def send_test_prompt(self):
        prompt = self.prompt_entry.get().strip()
        if not prompt:
            return

        self.prompt_entry.delete(0, ctk.END)
        self.send_prompt_btn.configure(state="disabled")
        
        # Enable console and insert prompt
        self.test_console.configure(state="normal")
        self.test_console.insert("end", f"\n>>> User: {prompt}\n")
        self.test_console.insert("end", "[System] Agent is thinking...\n")
        self.test_console.see("end")
        self.test_console.configure(state="disabled")

        # Run in worker thread so the UI doesn't freeze during API request
        def worker():
            try:
                # Import agent here to avoid circular imports or early setup issues
                from nexuslink.server.agent_orchestrator import agent
                
                # Execute NLP prompt
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(agent.execute_command(prompt))
                loop.close()
                
                # Update UI in main thread safely
                self.after(0, lambda: self.append_test_result(f"[Agent Result]\n{result}\n"))
            except Exception as e:
                self.after(0, lambda: self.append_test_result(f"[Error] {e}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def append_test_result(self, text):
        self.test_console.configure(state="normal")
        self.test_console.insert("end", text)
        self.test_console.see("end")
        self.test_console.configure(state="disabled")
        self.send_prompt_btn.configure(state="normal")

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


if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
