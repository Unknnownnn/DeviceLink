import threading
import asyncio
import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from nexuslink.settings_manager import SettingsManager
from main import run as run_backend

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def create_tray_image():
    # Simple icon for the tray
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse((8, 8, 56, 56), fill=(0, 200, 255))
    return image


class DeviceLinkApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DeviceLink Dashboard")
        self.geometry("700x500")
        self.settings = SettingsManager()

        # Handle window close behavior
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Build UI
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=20, fill="both", expand=True)

        self.tab_status = self.tabview.add("Status")
        self.tab_rules = self.tabview.add("AI Apps & Shortcuts")

        self._build_status_tab()
        self._build_rules_tab()

        # Start backend
        self.backend_thread = threading.Thread(target=self.start_backend, daemon=True)
        self.backend_thread.start()

        # Tray Setup
        self.setup_tray()

    def _build_status_tab(self):
        label = ctk.CTkLabel(self.tab_status, text="DeviceLink is running in the background.", font=ctk.CTkFont(size=20, weight="bold"))
        label.pack(pady=40)

        info = ctk.CTkLabel(self.tab_status, text="Close this window to minimize to the System Tray.\nOpen the Android app to connect.", text_color="gray")
        info.pack()

    def _build_rules_tab(self):
        self.rules_frame = ctk.CTkScrollableFrame(self.tab_rules)
        self.rules_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_rules_ui()

    def refresh_rules_ui(self):
        for widget in self.rules_frame.winfo_children():
            widget.destroy()

        # Section: AI Apps
        ctk.CTkLabel(self.rules_frame, text="Permitted AI Applications", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 10))
        apps = self.settings.get_approved_apps()
        
        for name, exe in apps.items():
            row = ctk.CTkFrame(self.rules_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"{name.title()} ({exe})").pack(side="left")
            ctk.CTkButton(row, text="Remove", width=60, fg_color="#E74C3C", hover_color="#C0392B", 
                          command=lambda n=name: self.remove_app(n)).pack(side="right")

        # Add New App Form
        add_frame = ctk.CTkFrame(self.rules_frame, fg_color="transparent")
        add_frame.pack(fill="x", pady=10)
        self.app_name_entry = ctk.CTkEntry(add_frame, placeholder_text="App Name (e.g. Notepad)")
        self.app_name_entry.pack(side="left", padx=5, expand=True, fill="x")
        self.app_exe_entry = ctk.CTkEntry(add_frame, placeholder_text="Target (e.g. notepad.exe or Steam ID)")
        self.app_exe_entry.pack(side="left", padx=5, expand=True, fill="x")
        
        ctk.CTkButton(add_frame, text="Browse", width=60, command=self.browse_exe).pack(side="left", padx=5)
        
        # Determine type
        self.app_type_var = ctk.StringVar(value="app")
        ctk.CTkOptionMenu(add_frame, values=["app", "steam"], variable=self.app_type_var, width=80).pack(side="left", padx=5)

        ctk.CTkButton(add_frame, text="Add Shortcut", width=100, command=self.add_app).pack(side="right", padx=5)

    def browse_exe(self):
        filepath = ctk.filedialog.askopenfilename(
            title="Select Executable",
            filetypes=[("Executables", "*.exe"), ("All Files", "*.*")]
        )
        if filepath:
            self.app_exe_entry.delete(0, ctk.END)
            self.app_exe_entry.insert(0, filepath)

    def remove_app(self, name):
        # We find and remove the deck shortcut with this name
        shortcuts = self.settings.get_deck_shortcuts()
        for s in shortcuts:
            if s["id"].lower() == name.lower():
                self.settings.remove_shortcut(s["id"])
        self.settings.remove_app(name)
        self.refresh_rules_ui()

    def add_app(self):
        name = self.app_name_entry.get().strip()
        exe = self.app_exe_entry.get().strip()
        item_type = self.app_type_var.get()
        if name and exe:
            # Add to approved AI apps
            self.settings.add_app(name, exe)
            # Also add it as a deck shortcut so it syncs to android
            shortcut_id = name.lower()
            self.settings.add_shortcut(shortcut_id, name.title(), item_type, exe)
            
            # Clear entries to give visual feedback
            self.app_name_entry.delete(0, ctk.END)
            self.app_exe_entry.delete(0, ctk.END)
            
            self.refresh_rules_ui()

    def start_backend(self):
        # Run asyncio event loop for the server
        asyncio.run(run_backend(47200))

    def setup_tray(self):
        image = create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self.show_window),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("DeviceLink", image, "DeviceLink Agent", menu)
        # Run tray in separate thread so it doesn't block GUI
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.withdraw()

    def show_window(self):
        self.after(0, self.deiconify)

    def quit_app(self):
        self.tray_icon.stop()
        self.quit()
        sys.exit(0)


if __name__ == "__main__":
    app = DeviceLinkApp()
    app.mainloop()
