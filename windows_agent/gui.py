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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr
)

import threading
import asyncio
import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw
import os
import re

sys.path.insert(0, os.path.dirname(__file__))

from nexuslink.settings_manager import SettingsManager
from main import run as run_backend

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def create_tray_image():
    # Load custom icon.png if it exists
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    custom_icon = os.path.join(base_path, "icon.png")
    if os.path.exists(custom_icon):
        try:
            return Image.open(custom_icon)
        except Exception:
            pass

    # Simple icon for the tray
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse((8, 8, 56, 56), fill=(0, 200, 255))
    return image


class DeviceLinkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DeviceLink Dashboard")
        self.geometry("1050x650")
        self.resizable(False, False)
        self.settings = SettingsManager()
        self.check_single_instance()

        # Load window icon if it exists
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

        # Handle window close behavior
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Redirect standard output state
        self.log_history = []
        self.logs_window = None
        self.log_textbox = None

        # Build UI
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)

        self.tab_status = self.tabview.add("Status")
        self.tab_rules = self.tabview.add("AI Apps & Shortcuts")

        self._build_status_tab()
        self._build_rules_tab()

        # Start queue processing
        self.check_logs_loop()

        # Start backend
        self.backend_thread = threading.Thread(target=self.start_backend, daemon=True)
        self.backend_thread.start()

        # Tray Setup
        self.setup_tray()

        # Start connection status observer loop
        self.update_connection_status_loop()

    def _build_status_tab(self):
        # Title and info frame
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

        # Connection status badge
        self.conn_status_frame = ctk.CTkFrame(status_frame, fg_color="#1E293B", height=32, corner_radius=6)
        self.conn_status_frame.pack(anchor="w", pady=(0, 20))
        
        self.status_dot = ctk.CTkLabel(
            self.conn_status_frame, 
            text="●", 
            text_color="#F59E0B", # Orange/yellow for waiting
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

        # Button Row
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
            command=self.send_file_to_device
        )
        self.send_file_btn.pack(side="left", padx=(0, 10))

        self.show_logs_btn = ctk.CTkButton(
            button_row, 
            text="Show System Logs", 
            width=160, 
            command=self.show_logs_window
        )
        self.show_logs_btn.pack(side="left")

        # Settings & Preferences Section
        options_frame = ctk.CTkFrame(self.tab_status)
        options_frame.pack(fill="x", padx=10, pady=20)
        
        ctk.CTkLabel(
            options_frame, 
            text="Preferences", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        self.startup_var = ctk.BooleanVar(value=self.is_run_on_startup_enabled())
        self.startup_switch = ctk.CTkSwitch(
            options_frame, 
            text="Launch DeviceLink automatically on system startup", 
            variable=self.startup_var,
            command=self.toggle_startup
        )
        self.startup_switch.pack(anchor="w", padx=15, pady=(5, 15))

    def show_qr_code(self):
        from config import DEVICELINK_DIR
        qr_path = DEVICELINK_DIR / "pairing_qr.png"
        
        # Create TopLevel window
        qr_window = ctk.CTkToplevel(self)
        qr_window.title("Pairing QR Code")
        qr_window.geometry("340x420")
        qr_window.resizable(False, False)
        
        # Ensure it stays on top
        qr_window.attributes("-topmost", True)

        if qr_path.exists():
            try:
                # Load image using PIL
                pil_img = Image.open(str(qr_path))
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(260, 260))
                
                img_label = ctk.CTkLabel(qr_window, image=ctk_img, text="")
                img_label.image = ctk_img  # Keep reference
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
        # Check if window already exists and is open
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
        import shutil
        from nexuslink.server.dropzone_watcher import get_uploads_dir
        
        filepath = ctk.filedialog.askopenfilename(
            title="Select File to Send to Device"
        )
        if filepath:
            try:
                uploads_dir = get_uploads_dir()
                filename = os.path.basename(filepath)
                dest_path = uploads_dir / filename
                
                # Copy file to dropzone uploads directory
                shutil.copy(filepath, str(dest_path))
                
                print(f"[Console] Staged '{filename}' in DropZone. Sending...")
            except Exception as e:
                print(f"[Console] Error staging file: {e}")

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
            
        # Optimize performance: if the main dashboard is hidden and the logs window is closed,
        # slow down the polling interval (e.g. 2000ms instead of 150ms) to minimize CPU wakeups.
        is_visible = self.winfo_viewable()
        is_logs_open = self.logs_window and self.logs_window.winfo_exists()
        interval = 150 if (is_visible or is_logs_open) else 2000
        
        self.after(interval, self.check_logs_loop)

    def update_connection_status_loop(self):
        try:
            from nexuslink.server.ws_server import get_active_peers
            peers = get_active_peers()
            if peers:
                peer_str = ", ".join(f"{p[0]}:{p[1]}" for p in peers)
                self.status_dot.configure(text_color="#10B981") # Green
                self.status_text.configure(text=f"Connected to {peer_str}")
            else:
                self.status_dot.configure(text_color="#F59E0B") # Yellow/Orange
                self.status_text.configure(text="Waiting for Android connection...")
        except Exception:
            pass
            
        self.after(1000, self.update_connection_status_loop)

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
        # Container frame for two columns
        self.rules_container = ctk.CTkFrame(self.tab_rules, fg_color="transparent")
        self.rules_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Configure columns (1 row, 2 columns)
        self.rules_container.grid_columnconfigure(0, weight=1, uniform="rules_col")
        self.rules_container.grid_columnconfigure(1, weight=1, uniform="rules_col")
        self.rules_container.grid_rowconfigure(0, weight=1)

        # Left Column: AI Allowed Apps
        self.ai_col_frame = ctk.CTkFrame(self.rules_container)
        self.ai_col_frame.grid(row=0, column=0, padx=(0, 10), sticky="nsew")

        # Right Column: Shortcuts Menu
        self.shortcuts_col_frame = ctk.CTkFrame(self.rules_container)
        self.shortcuts_col_frame.grid(row=0, column=1, padx=(10, 0), sticky="nsew")

        self.refresh_rules_ui()

    def refresh_rules_ui(self):
        # 1. Clear previous content
        for widget in self.ai_col_frame.winfo_children():
            widget.destroy()
        for widget in self.shortcuts_col_frame.winfo_children():
            widget.destroy()

        # ── LEFT COLUMN: AI Allowed Applications ───────────────────────
        ctk.CTkLabel(
            self.ai_col_frame, 
            text="AI Allowed Applications / Tools", 
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Add AI App Form Container (pack bottom first!)
        ai_add_frame = ctk.CTkFrame(self.ai_col_frame, fg_color="transparent")
        ai_add_frame.pack(fill="x", side="bottom", padx=15, pady=(5, 15))

        self.ai_name_entry = ctk.CTkEntry(ai_add_frame, placeholder_text="App Name (e.g. spotify)")
        self.ai_name_entry.pack(fill="x", pady=2)

        ai_exe_row = ctk.CTkFrame(ai_add_frame, fg_color="transparent")
        ai_exe_row.pack(fill="x", pady=2)
        self.ai_exe_entry = ctk.CTkEntry(ai_exe_row, placeholder_text="Executable/Path (e.g. spotify.exe)")
        self.ai_exe_entry.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.ai_browse_btn = ctk.CTkButton(
            ai_exe_row, text="Browse", width=60, 
            command=lambda: self.browse_exe(self.ai_exe_entry)
        )
        self.ai_browse_btn.pack(side="left")

        # Type Row for AI Apps
        ai_type_row = ctk.CTkFrame(ai_add_frame, fg_color="transparent")
        ai_type_row.pack(fill="x", pady=2)
        ctk.CTkLabel(ai_type_row, text="Type:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        self.ai_type_var = ctk.StringVar(value="app")
        
        def on_ai_type_change(val):
            if val == "app":
                self.ai_browse_btn.configure(state="normal")
                self.ai_exe_entry.configure(placeholder_text="Executable/Path (e.g. spotify.exe)")
            elif val == "steam":
                self.ai_browse_btn.configure(state="disabled")
                self.ai_exe_entry.configure(placeholder_text="Steam App ID (e.g. 730)")
            elif val == "url":
                self.ai_browse_btn.configure(state="disabled")
                self.ai_exe_entry.configure(placeholder_text="Web URL (e.g. https://youtube.com)")

        self.ai_type_menu = ctk.CTkOptionMenu(
            ai_type_row, values=["app", "steam", "url"], 
            variable=self.ai_type_var, command=on_ai_type_change, width=80
        )
        self.ai_type_menu.pack(side="left", padx=5)

        ctk.CTkButton(
            ai_add_frame, text="Add AI Approved App", 
            command=self.add_ai_app
        ).pack(fill="x", pady=(5, 0))

        # Scrollable list for AI apps (pack to expand)
        ai_list_frame = ctk.CTkScrollableFrame(self.ai_col_frame, fg_color="transparent")
        ai_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        apps = self.settings.get_approved_apps()
        for name, exe in apps.items():
            row = ctk.CTkFrame(ai_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            
            # Pack buttons FIRST on the right to keep them fixed in place
            # Remove button
            ctk.CTkButton(
                row, text="Remove", width=55, height=22, fg_color="#E74C3C", hover_color="#C0392B", 
                command=lambda n=name: self.remove_ai_app(n)
            ).pack(side="right", padx=2)
            
            # Edit button
            ctk.CTkButton(
                row, text="Edit", width=45, height=22, fg_color="#3498DB", hover_color="#2980B9", 
                command=lambda n=name, e=exe: self.edit_ai_app_window(n, e)
            ).pack(side="right", padx=2)
            
            # Pack label on the left (show type in brackets)
            app_type = "app"
            if exe.isdigit():
                app_type = "steam"
            elif exe.startswith("http://") or exe.startswith("https://"):
                app_type = "url"
            display_name = f"{name.title()} [{app_type}]"
            ctk.CTkLabel(row, text=display_name, font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left", padx=5, fill="x", expand=True)

        # ── RIGHT COLUMN: Mobile Client Shortcuts ──────────────────────
        ctk.CTkLabel(
            self.shortcuts_col_frame, 
            text="Mobile Deck Shortcuts", 
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Add Shortcut Form Container (pack bottom first!)
        sc_add_frame = ctk.CTkFrame(self.shortcuts_col_frame, fg_color="transparent")
        sc_add_frame.pack(fill="x", side="bottom", padx=15, pady=(5, 15))

        self.sc_name_entry = ctk.CTkEntry(sc_add_frame, placeholder_text="Shortcut Label (e.g. Play CS2)")
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

    def remove_shortcut(self, shortcut_id):
        self.settings.remove_shortcut(shortcut_id)
        self.refresh_rules_ui()

    def check_single_instance(self):
        self.lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
            except Exception:
                pass
            sys.exit(0)

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
            pystray.MenuItem("Show Dashboard", self.show_window),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("DeviceLink", image, "DeviceLink Agent", menu)
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
        enabled = self.startup_var.get()
        
        if getattr(sys, 'frozen', False):
            exe_path = f'"{sys.executable}"'
        else:
            script_path = os.path.abspath(sys.argv[0])
            exe_path = f'"{sys.executable}" "{script_path}"'
            
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


if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
