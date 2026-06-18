import json
import os
import threading
from pathlib import Path

from config import DEVICELINK_DIR

class SettingsManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SettingsManager, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self.settings_file = DEVICELINK_DIR / "settings.json"
        self.default_settings = {
            "openrouter_api_key": "",
            "openrouter_model": "google/gemini-2.5-flash",
            "allowed_launch_dirs": [
                "C:\\Games",
                "D:\\",
                "E:\\"
            ],
            "approved_apps": {
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "explorer": "explorer.exe"
            },
            "deck_shortcuts": [
                {"id": "notepad", "label": "Notepad", "type": "app", "target": "notepad.exe"},
                {"id": "calculator", "label": "Calculator", "type": "app", "target": "calc.exe"},
                {"id": "steam", "label": "Steam (CS2)", "type": "steam", "target": "730"}
            ]
        }
        self.settings = self.load()

    def load(self):
        if not self.settings_file.exists():
            self.save(self.default_settings)
            return self.default_settings.copy()
        try:
            with open(self.settings_file, "r") as f:
                data = json.load(f)
                # Merge with defaults to ensure keys exist
                for k, v in self.default_settings.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            return self.default_settings.copy()

    def save(self, data=None):
        if data is not None:
            self.settings = data
        with open(self.settings_file, "w") as f:
            json.dump(self.settings, f, indent=4)

    def get_approved_apps(self):
        # Return standard apps ONLY (segregated from mobile shortcuts)
        return self.settings.get("approved_apps", {}).copy()
    
    def get_deck_shortcuts(self):
        return self.settings.get("deck_shortcuts", [])
    
    def add_app(self, name, exe):
        self.settings["approved_apps"][name.lower()] = exe
        self.save()

    def remove_app(self, name):
        name_lower = name.lower()
        if name_lower in self.settings["approved_apps"]:
            del self.settings["approved_apps"][name_lower]
            self.save()

    def add_shortcut(self, shortcut_id, label, item_type, target):
        self.settings["deck_shortcuts"].append({
            "id": shortcut_id,
            "label": label,
            "type": item_type,
            "target": target
        })
        self.save()

    def remove_shortcut(self, shortcut_id):
        self.settings["deck_shortcuts"] = [
            s for s in self.settings["deck_shortcuts"] if s["id"] != shortcut_id
        ]
        self.save()

    def update_app(self, old_name, new_name, new_exe):
        old_name_lower = old_name.lower()
        new_name_lower = new_name.lower()
        if old_name_lower in self.settings["approved_apps"]:
            if old_name_lower != new_name_lower:
                del self.settings["approved_apps"][old_name_lower]
            self.settings["approved_apps"][new_name_lower] = new_exe
            self.save()
            return True
        return False

    def update_shortcut(self, old_id, new_label, new_type, new_target, custom_icon=None):
        shortcuts = self.settings.get("deck_shortcuts", [])
        for s in shortcuts:
            if s["id"] == old_id:
                s["label"] = new_label
                s["type"] = new_type
                s["target"] = new_target
                if custom_icon:
                    s["custom_icon"] = custom_icon
                elif "custom_icon" in s:
                    del s["custom_icon"]
                new_id = new_label.lower().replace(" ", "_")
                s["id"] = new_id
                self.save()
                return True
        return False

    def get_openrouter_api_key(self) -> str:
        return self.settings.get("openrouter_api_key", "")

    def get_openrouter_model(self) -> str:
        return self.settings.get("openrouter_model", "google/gemini-2.5-flash")

    def update_openrouter_settings(self, api_key: str, model: str) -> None:
        self.settings["openrouter_api_key"] = api_key.strip()
        self.settings["openrouter_model"] = model.strip()
        self.save()
