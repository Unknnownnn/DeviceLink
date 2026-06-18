import asyncio
import json
import logging
import os
import subprocess
import webbrowser
import shlex
from pathlib import Path
from typing import Dict, Any, List

import aiohttp
from websockets.server import WebSocketServerProtocol

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry
from nexuslink.settings_manager import SettingsManager

log = logging.getLogger("nexuslink.orchestrator")

active_consents: Dict[str, tuple] = {}


class SanitizationSandbox:
    """
    Executes tool calls strictly ensuring path-jailing and process whitelisting.
    NEVER uses shell=True.
    """
    def __init__(self):
        self.settings = SettingsManager()

    @staticmethod
    def _resolve_safe_path(relative_path: str) -> Path:
        r"""
        Resolves a relative path strictly within the user's home profile.
        Strict Guardrail: Absolutely prevents writing, reading, or deleting files in sensitive 
        system directories like C:\Windows, C:\Program Files, etc., by jailing execution 
        strictly inside the User Profile directory (C:\Users\<username>).
        """
        base_path = Path.home()
        clean_rel = relative_path.lstrip("\\/")
        target = (base_path / clean_rel).resolve()
        
        if not target.is_relative_to(base_path):
            raise PermissionError(f"Path traversal detected! {target} is outside of user profile.")
        return target

    def create_local_directory(self, relative_path: str) -> str:
        try:
            target = self._resolve_safe_path(relative_path)
            if target.exists():
                return f"Directory already exists: {target}"
            target.mkdir(parents=True, exist_ok=True)
            return f"Successfully created directory: {target}"
        except Exception as e:
            return f"Failed to create directory: {e}"

    def count_directory_files(self, relative_path: str) -> str:
        try:
            target = self._resolve_safe_path(relative_path)
            if not target.exists() or not target.is_dir():
                return f"Target is not a valid directory: {target}"
            
            count = sum(1 for item in target.iterdir() if item.is_file())
            return f"Found {count} files in {target}"
        except Exception as e:
            return f"Failed to count files: {e}"

    async def list_directory_contents(self, path: str, is_remote: bool = False) -> str:
        try:
            import os
            path = path.strip()
            
            # Rewrite username if needed
            import re
            actual_username = os.path.basename(str(Path.home()))
            match = re.match(r'(?i)^([a-z]:[\\/]users[\\/])([^\\/]+)(.*)$', path)
            if match:
                prefix, path_username, rest = match.groups()
                if path_username.lower() != actual_username.lower():
                    path = prefix + actual_username + rest
                    
            # Check if drive is specified. If not, resolve relative to home directory
            has_drive = len(path) > 1 and path[1] == ':'
            if not has_drive:
                clean_path = path.lstrip("\\/")
                resolved_path = os.path.join(str(Path.home()), clean_path)
            else:
                resolved_path = path
                
            resolved_path = os.path.abspath(resolved_path)
            resolved_lower = resolved_path.lower()
            
            # Check if the path is inside the user profile directory
            base_path = str(Path.home()).lower()
            is_inside_user_profile = resolved_lower.startswith(base_path)
            
            # If outside the user profile, require user consent
            if not is_inside_user_profile:
                import uuid
                consent_id = str(uuid.uuid4())
                
                consent_payload = {
                    "consent_id": consent_id,
                    "target": resolved_path,
                    "arguments": "",
                    "app_desc": f"View directory contents of: {resolved_path}"
                }
                
                if is_remote:
                    from nexuslink.server.ws_server import send_to_all_peers
                    await send_to_all_peers("launch_consent_request", consent_payload)
                
                event = asyncio.Event()
                consent_status = {"approved": None}
                active_consents[consent_id] = (event, consent_status)
                
                pc_task = None
                if not is_remote:
                    async def run_pc_dialog():
                        import ctypes
                        MB_YESNO = 0x04
                        MB_ICONQUESTION = 0x20
                        MB_TOPMOST = 0x40000
                        IDYES = 6
                        
                        title = "AI Agent Directory Access Consent"
                        message = f"The AI Agent is requesting permission to view files in a folder outside your profile:\n\n{resolved_path}\n\nDo you want to allow this?"
                        
                        res = await asyncio.to_thread(ctypes.windll.user32.MessageBoxW, 0, message, title, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST)
                        if not event.is_set():
                            consent_status["approved"] = (res == IDYES)
                            event.set()
                            
                    pc_task = asyncio.create_task(run_pc_dialog())
                    
                try:
                    await event.wait()
                finally:
                    active_consents.pop(consent_id, None)
                    if pc_task and not pc_task.done():
                        import ctypes
                        hwnd = ctypes.windll.user32.FindWindowW(None, "AI Agent Directory Access Consent")
                        if hwnd:
                            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    if is_remote:
                        from nexuslink.server.ws_server import send_to_all_peers
                        await send_to_all_peers("launch_consent_cancel", {"consent_id": consent_id})
                    
                if not consent_status["approved"]:
                    return f"Access Denied: User rejected permission to view directory '{resolved_path}'."
                    
            if not os.path.exists(resolved_path):
                return f"Error: Directory does not exist: {resolved_path}"
                
            if not os.path.isdir(resolved_path):
                return f"Error: Path is a file, not a directory: {resolved_path}"
                
            # List directory items
            items = os.listdir(resolved_path)
            if not items:
                return f"Directory '{resolved_path}' is empty."
                
            files_list = []
            dirs_list = []
            for item in items:
                full_item_path = os.path.join(resolved_path, item)
                if os.path.isdir(full_item_path):
                    dirs_list.append(item + "/")
                else:
                    files_list.append(item)
                    
            # Sort lists
            dirs_list.sort()
            files_list.sort()
            
            res_str = f"Contents of '{resolved_path}':\n"
            if dirs_list:
                res_str += f"Folders ({len(dirs_list)}):\n" + "\n".join([f"  - {d}" for d in dirs_list]) + "\n"
            if files_list:
                res_str += f"Files ({len(files_list)}):\n" + "\n".join([f"  - {f}" for f in files_list]) + "\n"
                
            return res_str
            
        except Exception as e:
            return f"Failed to list directory: {e}"

    async def delete_local_file(self, path: str, is_remote: bool = False) -> str:
        try:
            import os
            path = path.strip()
            
            # Rewrite username if needed
            import re
            actual_username = os.path.basename(str(Path.home()))
            match = re.match(r'(?i)^([a-z]:[\\/]users[\\/])([^\\/]+)(.*)$', path)
            if match:
                prefix, path_username, rest = match.groups()
                if path_username.lower() != actual_username.lower():
                    path = prefix + actual_username + rest
                    
            # Check if drive is specified. If not, resolve relative to home directory
            has_drive = len(path) > 1 and path[1] == ':'
            if not has_drive:
                clean_path = path.lstrip("\\/")
                resolved_path = os.path.join(str(Path.home()), clean_path)
            else:
                resolved_path = path
                
            resolved_path = os.path.abspath(resolved_path)
            
            # Deleting files is a destructive action: ALWAYS require consent
            import uuid
            consent_id = str(uuid.uuid4())
            
            consent_payload = {
                "consent_id": consent_id,
                "target": resolved_path,
                "arguments": "",
                "app_desc": f"DELETE file: {resolved_path}"
            }
            
            if is_remote:
                from nexuslink.server.ws_server import send_to_all_peers
                await send_to_all_peers("launch_consent_request", consent_payload)
            
            event = asyncio.Event()
            consent_status = {"approved": None}
            active_consents[consent_id] = (event, consent_status)
            
            pc_task = None
            if not is_remote:
                async def run_pc_dialog():
                    import ctypes
                    MB_YESNO = 0x04
                    MB_ICONQUESTION = 0x20
                    MB_TOPMOST = 0x40000
                    IDYES = 6
                    
                    title = "AI Agent File Deletion Consent"
                    message = f"The AI Agent is requesting permission to delete a file on your PC. Please Note this file will be PERMANENTLY DELETED and CANNOT BE RECOVERED:\n\n{resolved_path}\n\nDo you want to allow this?"
                    
                    res = await asyncio.to_thread(ctypes.windll.user32.MessageBoxW, 0, message, title, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST)
                    if not event.is_set():
                        consent_status["approved"] = (res == IDYES)
                        event.set()
                        
                pc_task = asyncio.create_task(run_pc_dialog())
                
            try:
                await event.wait()
            finally:
                active_consents.pop(consent_id, None)
                if pc_task and not pc_task.done():
                    import ctypes
                    hwnd = ctypes.windll.user32.FindWindowW(None, "AI Agent File Deletion Consent")
                    if hwnd:
                        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                if is_remote:
                    from nexuslink.server.ws_server import send_to_all_peers
                    await send_to_all_peers("launch_consent_cancel", {"consent_id": consent_id})
                
            if not consent_status["approved"]:
                return f"Access Denied: User rejected permission to delete file '{resolved_path}'."
                
            if not os.path.exists(resolved_path):
                return f"Error: File does not exist: {resolved_path}"
                
            if os.path.isdir(resolved_path):
                return f"Error: Path is a directory, not a file: {resolved_path}"
                
            os.remove(resolved_path)
            return f"Successfully deleted file: {resolved_path}"
            
        except Exception as e:
            return f"Failed to delete file: {e}"

    @staticmethod
    def _find_start_menu_shortcut(app_name: str):
        """
        Searches the Start Menu directories for a shortcut (.lnk) matching the given app name.
        Returns the absolute path to the .lnk file if found, otherwise None.
        """
        import os
        from pathlib import Path
        
        app_name_lower = app_name.lower().strip()
        
        start_menu_paths = [
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.path.expandvars("%APPDATA%")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        ]
        
        for start_path in start_menu_paths:
            if not start_path.exists():
                continue
            for root, dirs, files in os.walk(start_path):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        name_without_ext = file[:-4].lower()
                        if app_name_lower == name_without_ext or app_name_lower in name_without_ext:
                            return os.path.join(root, file)
        return None

    async def launch_application(self, target: str, arguments: str = "", is_remote: bool = False) -> str:
        """
        Launches an application or web URL.
        - Web URLs (http/https) are always allowed and opened in the default browser.
        - Whitelisted apps are launched directly.
        - Other executables are verified against safety guardrails before execution.
        """
        try:
            import shutil
            target = target.strip()
            
            # If the path starts with C:\Users\<placeholder> or similar, replace the username part with the actual username
            import re
            actual_username = os.path.basename(str(Path.home()))
            match = re.match(r'(?i)^([a-z]:[\\/]users[\\/])([^\\/]+)(.*)$', target)
            if match:
                prefix, path_username, rest = match.groups()
                if path_username.lower() != actual_username.lower():
                    target = prefix + actual_username + rest
            
            # Automatically resolve relative paths (or paths missing the drive/user profile prefix) relative to the user's home directory
            has_drive = len(target) > 1 and target[1] == ':'
            if not has_drive and not target.lower().startswith(("http://", "https://")):
                clean_target = target.lstrip("\\/")
                home_resolved = os.path.join(str(Path.home()), clean_target)
                first_part = clean_target.replace("/", "\\").split("\\")[0].lower()
                user_dirs = {"downloads", "documents", "desktop", "music", "videos", "pictures", "favorites", "links", "contacts", "searches", "saved games"}
                if os.path.exists(home_resolved) or first_part in user_dirs:
                    target = home_resolved
            
            if target.lower().startswith(("http://", "https://")):
                webbrowser.open(target)
                return f"Successfully opened web link: {target}"
                
            name_lower = target.lower()
            approved = self.settings.get_approved_apps()
            
            if name_lower in approved:
                exe = approved[name_lower]
                return self._execute_safe_exe(exe, arguments)
                
            # If not in approved list, dynamically search in Start Menu shortcuts
            shortcut_path = self._find_start_menu_shortcut(target)
            if shortcut_path:
                return self._execute_safe_exe(shortcut_path, arguments)
                
            resolved_exe = shutil.which(target) or target
            resolved_lower = resolved_exe.lower()
            
            blocked_binaries = [
                "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
                "reg.exe", "regedit.exe", "mshta.exe", "schtasks.exe", "sc.exe", 
                "bash.exe", "sh.exe", "cmd", "powershell"
            ]
            
            if any(blocked in resolved_lower for blocked in blocked_binaries):
                return f"Security Blocked: Direct execution of shell script interpreters or registry editors is prohibited for safety reasons."
                
            allowed_directories = [
                os.environ.get("SystemRoot", "C:\\Windows").lower(),
                os.environ.get("ProgramFiles", "C:\\Program Files").lower(),
                os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower(),
                os.environ.get("ProgramData", "C:\\ProgramData").lower(),
                os.path.expandvars("%APPDATA%").lower(),
                os.path.expandvars("%LOCALAPPDATA%").lower(),
                str(Path.home() / "Desktop").lower(),
                "c:\\users\\public\\desktop",
            ]
            
            custom_dirs = self.settings.settings.get("allowed_launch_dirs", [])
            for c_dir in custom_dirs:
                if c_dir:
                    allowed_directories.append(c_dir.lower().strip())
            
            is_safe_dir = False
            if os.path.isabs(resolved_exe):
                resolved_dir = os.path.dirname(resolved_exe).lower()
                is_safe_dir = any(resolved_dir.startswith(allowed) for allowed in allowed_directories)
                
            # If not whitelisted or in allowed folders, prompt user for security consent
            if not is_safe_dir:
                import uuid
                consent_id = str(uuid.uuid4())
                
                app_desc = target
                if arguments:
                    app_desc += f" {arguments}"
                    
                consent_payload = {
                    "consent_id": consent_id,
                    "target": target,
                    "arguments": arguments,
                    "app_desc": app_desc
                }
                
                if is_remote:
                    from nexuslink.server.ws_server import send_to_all_peers
                    await send_to_all_peers("launch_consent_request", consent_payload)
                
                event = asyncio.Event()
                consent_status = {"approved": None}
                active_consents[consent_id] = (event, consent_status)
                
                pc_task = None
                if not is_remote:
                    async def run_pc_dialog():
                        import ctypes
                        MB_YESNO = 0x04
                        MB_ICONQUESTION = 0x20
                        MB_TOPMOST = 0x40000
                        IDYES = 6
                        
                        title = "AI Agent Security Consent"
                        message = f"The AI Agent is requesting permission to launch an app located outside your approved directories:\n\n{app_desc}\n\nDo you want to allow this launch?"
                        
                        res = await asyncio.to_thread(ctypes.windll.user32.MessageBoxW, 0, message, title, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST)
                        
                        if not event.is_set():
                            consent_status["approved"] = (res == IDYES)
                            event.set()
                    
                    pc_task = asyncio.create_task(run_pc_dialog())
                
                try:
                    await event.wait()
                finally:
                    active_consents.pop(consent_id, None)
                    if pc_task and not pc_task.done():
                        # Close the PC dialog programmatically if the event was set by the mobile device
                        import ctypes
                        hwnd = ctypes.windll.user32.FindWindowW(None, "AI Agent Security Consent")
                        if hwnd:
                            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    # Close mobile dialog if it is still open
                    if is_remote:
                        from nexuslink.server.ws_server import send_to_all_peers
                        await send_to_all_peers("launch_consent_cancel", {"consent_id": consent_id})
                
                if not consent_status["approved"]:
                    return f"Launch Rejected: User denied permission to launch '{target}'."
            
            return self._execute_safe_exe(resolved_exe, arguments)
            
        except Exception as e:
            return f"Failed to launch: {e}"

    def _execute_safe_exe(self, exe: str, arguments: str) -> str:
        if exe.isdigit():
            webbrowser.open(f"steam://run/{exe}")
            return f"Successfully routed launch request for Steam game ID: {exe}"
        elif exe.lower().startswith(("http://", "https://")):
            webbrowser.open(exe)
            return f"Successfully opened web link: {exe}"
        elif exe.lower().endswith((".lnk", ".url")) or exe.lower().startswith("shell:") or (":" in exe and not exe.startswith(("http://", "https://")) and exe.split(":")[0].isalnum()):
            try:
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(None, "open", exe, arguments or None, None, 1)
                return f"Successfully opened target via ShellExecute: {exe}"
            except Exception as e:
                return f"Failed to open target via ShellExecute: {e}"
        else:
            args = shlex.split(exe, posix=False)
            if arguments:
                args.extend(shlex.split(arguments, posix=False))
            try:
                subprocess.Popen(args, shell=False)
                return f"Successfully launched app: {exe} {arguments}".strip()
            except PermissionError as e:
                if hasattr(e, 'winerror') and e.winerror == 740:
                    import ctypes
                    executable_path = args[0]
                    exec_args = " ".join(args[1:])
                    ctypes.windll.shell32.ShellExecuteW(None, "runas", executable_path, exec_args, None, 1)
                    return f"Launch requires admin privileges. Sent UAC elevation prompt on PC."
                else:
                    raise e

    def launch_shortcut_application(self, shortcut_id: str) -> str:
        try:
            id_lower = shortcut_id.lower().strip()
            deck_shortcuts = self.settings.get_deck_shortcuts()
            
            shortcut = None
            for s in deck_shortcuts:
                if s["id"].lower() == id_lower:
                    shortcut = s
                    break
            
            if not shortcut:
                return f"Rejected: Mobile shortcut '{shortcut_id}' is not configured."

            exe = shortcut["target"]
            is_steam = shortcut["type"] == "steam"
            
            if is_steam:
                uri = f"steam://run/{exe}"
                webbrowser.open(uri)
                return f"Successfully routed shortcut launch request for Steam game: {shortcut_id}"
            elif exe.startswith("http://") or exe.startswith("https://"):
                webbrowser.open(exe)
                return f"Successfully opened shortcut web link: {shortcut_id}"
            elif exe.lower().endswith((".lnk", ".url")) or exe.lower().startswith("shell:") or (":" in exe and not exe.startswith(("http://", "https://")) and exe.split(":")[0].isalnum()):
                try:
                    import ctypes
                    ctypes.windll.shell32.ShellExecuteW(None, "open", exe, None, None, 1)
                    return f"Successfully launched shortcut target: {shortcut_id}"
                except Exception as e:
                    return f"Failed to launch shortcut target via ShellExecute: {e}"
            else:
                args = shlex.split(exe, posix=False)
                try:
                    subprocess.Popen(args, shell=False)
                    return f"Successfully launched shortcut local app: {shortcut_id}"
                except PermissionError as e:
                    if hasattr(e, 'winerror') and e.winerror == 740:
                        import ctypes
                        executable_path = args[0]
                        exec_args = " ".join(args[1:])
                        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable_path, exec_args, None, 1)
                        return f"Launch requires admin privileges. Sent UAC elevation prompt on PC for shortcut: {shortcut_id}."
                    else:
                        raise e
        except Exception as e:
            return f"Failed to launch shortcut application: {e}"

    def search_for_application(self, name: str) -> str:
        """
        Searches for applications, games, or shortcuts matching the given name in:
        - The user and public Desktop (shortcuts)
        - Start Menu directories
        - Configured custom allowed launch directories (e.g., C:\\Games, D:\\)
        Returns a list of matching file paths that can be passed to launch_application.
        """
        try:
            query_words = [w.lower() for w in name.split() if w.strip()]
            if not query_words:
                return "Error: search name cannot be empty"

            matches = []
            search_roots = []
            
            desktop_path = Path.home() / "Desktop"
            if desktop_path.exists():
                search_roots.append((desktop_path, False)) 
            
            public_desktop = Path("C:/Users/Public/Desktop")
            if public_desktop.exists():
                search_roots.append((public_desktop, False))
                
            start_menu_user = Path(os.path.expandvars("%APPDATA%")) / "Microsoft/Windows/Start Menu/Programs"
            if start_menu_user.exists():
                search_roots.append((start_menu_user, True))
                
            start_menu_common = Path(os.path.expandvars("%ProgramData%")) / "Microsoft/Windows/Start Menu/Programs"
            if start_menu_common.exists():
                search_roots.append((start_menu_common, True))

            custom_dirs = self.settings.settings.get("allowed_launch_dirs", [])
            for c_dir in custom_dirs:
                c_path = Path(c_dir)
                if c_path.exists():
                    search_roots.append((c_path, True))

            for root, recursive in search_roots:
                if len(matches) >= 15:
                    break
                
                try:
                    if recursive:
                        for dirpath, _, filenames in os.walk(root):
                            if len(matches) >= 15:
                                break
                            parts_lower = [p.lower() for p in Path(dirpath).parts]
                            if any(p.startswith('.') or p in ('$recycle.bin', 'system volume information') for p in parts_lower):
                                continue
                            
                            for f in filenames:
                                f_lower = f.lower()
                                if f_lower.endswith((".exe", ".lnk", ".url")):
                                    if all(word in f_lower for word in query_words):
                                        full_path = os.path.join(dirpath, f)
                                        matches.append(full_path)
                    else:
                        for item in root.iterdir():
                            if len(matches) >= 15:
                                break
                            if item.is_file() and item.suffix.lower() in (".exe", ".lnk", ".url"):
                                item_name_lower = item.name.lower()
                                if all(word in item_name_lower for word in query_words):
                                    matches.append(str(item))
                except Exception:
                    pass

            if not matches:
                return f"Could not find any shortcuts or executables matching '{name}'."
                
            res_list = "\n".join(f"- {m}" for m in matches)
            return f"Found {len(matches)} matching application(s):\n{res_list}\n\nYou can launch any of these using the launch_application tool by passing the full path as the target."
        except Exception as e:
            return f"Search failed: {e}"

    def close_application(self, target: str) -> str:
        """
        Closes an application or window matching the target string.
        - Uses a graceful window close (ctypes WM_CLOSE) based on window title matching.
        - Falls back to taskkill /F /IM name.exe for direct process termination.
        """
        try:
            target = target.strip().lower()
            if not target:
                return "Error: target cannot be empty"

            if target.startswith(("http://", "https://")):
                from urllib.parse import urlparse
                try:
                    parsed = urlparse(target)
                    host = parsed.netloc or parsed.path
                    if host.startswith("www."):
                        host = host[4:]
                    parts = host.split(".")
                    if len(parts) > 1:
                        target = parts[0]
                    else:
                        target = host
                except Exception:
                    pass

            closed_count = self._close_windows_by_title(target)
            if closed_count > 0:
                return f"Successfully closed {closed_count} window(s) matching '{target}' gracefully."
            common_mappings = {
                "word": "winword.exe",
                "excel": "excel.exe",
                "powerpoint": "powerpnt.exe",
                "edge": "msedge.exe",
                "chrome": "chrome.exe",
                "firefox": "firefox.exe",
                "spotify": "spotify.exe",
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
            }
            
            exe_names = []
            if target in common_mappings:
                exe_names.append(common_mappings[target])
            
            if not target.endswith(".exe"):
                exe_names.append(f"{target}.exe")
            exe_names.append(target)
            
            killed_any = False
            import subprocess
            for exe in exe_names:
                try:
                    res = subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, text=True, shell=False)
                    if res.returncode == 0:
                        killed_any = True
                except Exception:
                    pass
            
            if killed_any:
                return f"Successfully terminated processes matching '{target}'."
                
            return f"Could not find any running windows or processes matching '{target}' to close."
        except Exception as e:
            return f"Failed to close application: {e}"

    def _close_windows_by_title(self, search_str: str) -> int:
        import ctypes
        
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        PostMessageW = ctypes.windll.user32.PostMessageW
        
        WM_CLOSE = 0x0010
        closed_count = [0]
        
        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    
                    if search_str in title:
                        PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_count[0] += 1
            return True
            
        EnumWindows(EnumWindowsProc(foreach_window), 0)
        return closed_count[0]

    # ── Process listing & killing ──────────────────────────────────────────────

    # Blocked process names that should never be listed or killed
    BLOCKED_PROCESS_NAMES = {
        "system", "system idle process", "system interrupts", "registry",
        "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
        "services.exe", "lsass.exe", "svchost.exe", "dwm.exe",
        "ntoskrnl.exe", "hal.dll", "winload.exe", "bootmgr.exe",
        "conhost.exe", "fontdrvhost.exe", "sihost.exe",
        "taskhostw.exe", "dllhost.exe", "ctfmon.exe",
        "securityhealthservice.exe", "securityhealthsystray.exe",
    }

    def list_processes(self, filter_name: str = "") -> str:
        """
        Lists running processes, optionally filtered by name.
        Returns a numbered list with PID and process name.
        """
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, shell=False, timeout=10
            )
            if result.returncode != 0:
                return f"Failed to list processes: {result.stderr.strip()}"

            lines = result.stdout.strip().splitlines()
            processes = []
            for line in lines:
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    pid = parts[1].strip()
                    mem = parts[4].strip() if len(parts) > 4 else "?"
                    name_lower = name.lower()
                    # Skip blocked system-critical processes
                    if name_lower in self.BLOCKED_PROCESS_NAMES:
                        continue
                    # Skip very short PIDs or empty
                    if not pid.isdigit():
                        continue
                    # Apply filter if provided
                    if filter_name and filter_name.lower() not in name_lower:
                        continue
                    processes.append({"pid": int(pid), "name": name, "mem": mem})

            if not processes:
                if filter_name:
                    return f"No processes found matching '{filter_name}'."
                return "No processes found."

            # Build numbered output
            lines_out = []
            for i, p in enumerate(processes, 1):
                lines_out.append(f"{i}. PID {p['pid']}  {p['name']}  ({p['mem']})")

            header = f"Found {len(processes)} process(es)"
            if filter_name:
                header += f" matching '{filter_name}'"
            header += ":\n"
            return header + "\n".join(lines_out)

        except subprocess.TimeoutExpired:
            return "Failed to list processes: command timed out."
        except Exception as e:
            return f"Failed to list processes: {e}"

    def kill_processes(self, pids_or_names: str) -> str:
        """
        Kills one or more processes by PID or name.
        pids_or_names is a comma-separated list of PIDs (integers) or process names.
        """
        try:
            items = [item.strip() for item in pids_or_names.split(",") if item.strip()]
            if not items:
                return "Error: no PIDs or names provided."

            results = []
            for item in items:
                # Check if it's a PID (integer)
                if item.isdigit():
                    pid = int(item)
                    try:
                        res = subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, text=True, shell=False, timeout=10
                        )
                        if res.returncode == 0:
                            results.append(f"Killed PID {pid}")
                        else:
                            results.append(f"Could not kill PID {pid}: {res.stderr.strip()}")
                    except subprocess.TimeoutExpired:
                        results.append(f"Timeout killing PID {pid}")
                    except Exception as e:
                        results.append(f"Error killing PID {pid}: {e}")
                else:
                    # It's a process name
                    name_lower = item.lower()
                    if name_lower in self.BLOCKED_PROCESS_NAMES:
                        results.append(f"Blocked: cannot kill system-critical process '{item}'")
                        continue
                    try:
                        res = subprocess.run(
                            ["taskkill", "/F", "/IM", item],
                            capture_output=True, text=True, shell=False, timeout=10
                        )
                        if res.returncode == 0:
                            results.append(f"Killed process '{item}'")
                        else:
                            results.append(f"Could not kill '{item}': {res.stderr.strip()}")
                    except subprocess.TimeoutExpired:
                        results.append(f"Timeout killing '{item}'")
                    except Exception as e:
                        results.append(f"Error killing '{item}': {e}")

            return "\n".join(results)

        except Exception as e:
            return f"Failed to kill processes: {e}"


class OpenRouterAgent:
    TOOLS_SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "create_local_directory",
                "description": "Creates a new folder at a relative path inside the user standard profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Relative directory layout string, e.g., 'Documents/Projects/App'"}
                    },
                    "required": ["relative_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "count_directory_files",
                "description": "Returns the integer count of files residing within an approved sub-folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Relative directory layout string, e.g., 'Downloads'"}
                    },
                    "required": ["relative_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "launch_application",
                "description": "Launch any application or open a web URL (e.g., youtube, google search, photoshop, steam, web links). For web links or searches, pass the full URL (e.g., https://youtube.com or https://youtube.com/results?search_query=...).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string", 
                            "description": "The name of the app, command, or full URL to open (e.g. 'notepad', 'https://youtube.com')."
                        },
                        "arguments": {
                            "type": "string",
                            "description": "Optional arguments to pass (e.g. file paths, web pages for browsers, search queries)."
                        }
                    },
                    "required": ["target"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "close_application",
                "description": "Close an application or a web URL (e.g., youtube, google search, photoshop, steam, web links). For web links, pass the full URL (e.g., https://youtube.com or https://youtube.com/results?search_query=...).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string", 
                            "description": "The name of the app, command, or full URL to close (e.g. 'notepad', 'word', 'https://youtube.com')."
                        },
                        "arguments": {
                            "type": "string",
                            "description": "Optional arguments to pass (e.g. file paths, web pages for browsers)."
                        }
                    },
                    "required": ["target"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_for_application",
                "description": "Search for shortcuts, games, or applications on the system Desktop, Start Menu, or custom allowed game/app folders (like C:\\Games or external drives) using key words.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Keywords matching the game or app name to find, e.g. 'days gone' or 'genshin'."
                        }
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_processes",
                "description": "List currently running processes on the system, optionally filtered by name. Returns a numbered list with PID, process name, and memory usage. Use this when the user wants to see or close background processes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter_name": {
                            "type": "string",
                            "description": "Optional keyword to filter processes by name (e.g. 'adobe', 'chrome'). Leave empty to list all processes."
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "kill_processes",
                "description": "Kill one or more running processes by PID or process name. Accepts a comma-separated list of PIDs (numbers) or process names (e.g. '1234,5678' or 'photoshop.exe,illustrator.exe'). IMPORTANT: When the user refers to numbered items from a previous list_processes result, you MUST resolve those numbers to the actual PIDs before calling this tool. Do NOT pass the list numbers themselves.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pids_or_names": {
                            "type": "string",
                            "description": "Comma-separated PIDs or process names to kill (e.g. '1234,5678' or 'photoshop.exe'). When the user picks numbers from a list_processes result, resolve them to the actual PIDs first."
                        }
                    },
                    "required": ["pids_or_names"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "control_android_device",
                "description": "Send control commands to the connected Android mobile device (e.g. launch apps, toggle flashlight, change volume, set alarms, dismiss alarms, create calendar events/tasks, delete calendar events/tasks, change silent/ringer mode).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["launch_app", "toggle_torch", "volume_control", "set_alarm", "dismiss_alarm", "create_calendar_event", "delete_calendar_event", "set_ringer_mode"],
                            "description": "The control action to execute on the Android device."
                        },
                        "package_or_app_name": {
                            "type": "string",
                            "description": "The package name or app name to launch (required only if action is 'launch_app')."
                        },
                        "state": {
                            "type": "boolean",
                            "description": "The boolean state to set (required only if action is 'toggle_torch')."
                        },
                        "stream": {
                            "type": "string",
                            "enum": ["media", "ring"],
                            "description": "The volume stream to adjust (required only if action is 'volume_control')."
                        },
                        "volume_level": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                            "description": "Volume percentage level from 0 to 100 (required only if action is 'volume_control')."
                        },
                        "alarm_hour": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 23,
                            "description": "Hour of alarm (0-23) (required only for action 'set_alarm', optional for 'dismiss_alarm')."
                        },
                        "alarm_minute": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 59,
                            "description": "Minute of alarm (0-59) (required only for action 'set_alarm', optional for 'dismiss_alarm')."
                        },
                        "alarm_message": {
                            "type": "string",
                            "description": "Label/title of the alarm (optional for action 'set_alarm' and 'dismiss_alarm')."
                        },
                        "event_title": {
                            "type": "string",
                            "description": "Title/subject of the calendar event/task (required for action 'create_calendar_event' and 'delete_calendar_event')."
                        },
                        "event_description": {
                            "type": "string",
                            "description": "Description/notes of the calendar event/task (optional for action 'create_calendar_event')."
                        },
                        "event_start_time": {
                            "type": "string",
                            "description": "ISO 8601 format date-time string (e.g. '2026-06-19T08:00:00') for event start time (required for action 'create_calendar_event')."
                        },
                        "event_end_time": {
                            "type": "string",
                            "description": "ISO 8601 format date-time string (e.g. '2026-06-19T09:00:00') for event end time (optional for action 'create_calendar_event')."
                        },
                        "ringer_mode": {
                            "type": "string",
                            "enum": ["normal", "vibrate", "silent"],
                            "description": "The target ringer mode (required only for action 'set_ringer_mode')."
                        }
                    },
                    "required": ["action"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory_contents",
                "description": "Lists the files and folders within a given directory (can be relative to the user profile or absolute).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The directory path to list, e.g. 'Downloads/OTHERS' or 'C:\\Users\\User\\Downloads'."
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_local_file",
                "description": "Deletes a file on the local PC. This is a destructive action and ALWAYS prompts the user for consent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The file path to delete (can be relative to the user profile or absolute)."
                        }
                    },
                    "required": ["path"]
                }
            }
        }
    ]

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.sandbox = SanitizationSandbox()
        self._conversation_history: List[Dict[str, Any]] = []
        self._max_history_messages = 30 

    async def execute_command(self, prompt: str, is_remote: bool = False) -> str:
        settings = SettingsManager()
        api_key = settings.get_openrouter_api_key()
        if not api_key:
            from config import OPENROUTER_API_KEY
            api_key = OPENROUTER_API_KEY
            
        model = settings.get_openrouter_model()
        if not model:
            from config import OPENROUTER_MODEL
            model = OPENROUTER_MODEL

        if not api_key:
            return "Server Error: OPENROUTER_API_KEY is not configured on the Windows agent. Please configure it in the agent dashboard Settings."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        system_instructions = (
            "You are a secure automation assistant. You can automate tasks on this Windows PC (launch programs, search for files, "
            "open URLs, list/kill processes) and also control the user's connected Android device (launch apps, toggle flashlight/torch, "
            "control ring/media volume) using the control_android_device tool.\n\n"
            "PROCESS MANAGEMENT FLOW:\n"
            "When the user asks to close/kill/stop processes (e.g. 'close all adobe processes'):\n"
            "1. Call list_processes with a filter_name matching what the user asked for.\n"
            "2. Present the numbered list to the user and ask which ones to close.\n"
            "3. When the user replies with numbers (e.g. '1, 3, 5'), resolve those numbers "
            "to the actual PIDs from the list you just showed, then call kill_processes with those PIDs.\n"
            "4. NEVER pass the list index numbers to kill_processes — always resolve them to real PIDs first.\n\n"
            "APP LAUNCH FLOW:\n"
            "To launch an app/game, first call search_for_application to locate it if you don't "
            "know the exact absolute path. Once you have the path from the search results, call launch_application "
            "passing the full path. Do NOT just output the search results to the user; proceed to launch the program.\n\n"
            "PRIVACY GUARDRAIL:\n"
            "You have absolutely NO access to the user's notifications, SMS messages, contacts, or call logs. "
            "Under no circumstances should you ever ask for, inspect, log, or process any notification or personal tray data."
        )
        
        # Append the new user message to conversation history
        self._conversation_history.append({"role": "user", "content": prompt})

        # Build the messages list: system + conversation history
        messages = [{"role": "system", "content": system_instructions}] + list(self._conversation_history)

        max_iterations = 5
        iteration = 0
        last_tool_output = ""

        try:
            async with aiohttp.ClientSession() as session:
                while iteration < max_iterations:
                    iteration += 1
                    payload = {
                        "model": model,
                        "messages": messages,
                        "tools": self.TOOLS_SCHEMA,
                        "tool_choice": "auto"
                    }
                    
                    async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as response:
                        if response.status != 200:
                            text = await response.text()
                            log.error("OpenRouter API error: %s", text)
                            if response.status == 429:
                                return f"AI API Error: HTTP 429 from OpenRouter (rate limited). {text[:500]}"
                            return f"AI API Error: HTTP {response.status}. {text[:500]}"
                        
                        data = await response.json()
                        choices = data.get("choices", [])
                        if not choices:
                            return "AI Error: Received empty response from model."
                            
                        message = choices[0].get("message", {})
                        
                        # Append assistant message
                        assistant_msg = {"role": "assistant"}
                        if message.get("content"):
                            assistant_msg["content"] = message.get("content")
                        if message.get("tool_calls"):
                            assistant_msg["tool_calls"] = message.get("tool_calls")
                        messages.append(assistant_msg)
                        self._conversation_history.append(assistant_msg)
                        
                        tool_calls = message.get("tool_calls", [])
                        if not tool_calls:
                            # No more tool calls, return the text content
                            # Trim conversation history to prevent unbounded growth
                            if len(self._conversation_history) > self._max_history_messages:
                                self._conversation_history = self._conversation_history[-self._max_history_messages:]
                            return message.get("content", "Command processed successfully.")
                        
                        tool_results = []
                        for call in tool_calls:
                            call_id = call.get("id")
                            func = call.get("function", {})
                            name = func.get("name")
                            args_str = func.get("arguments", "{}")
                            
                            try:
                                args = json.loads(args_str)
                            except json.JSONDecodeError:
                                args = {}

                            log.info("Agent executing tool: %s(%s)", name, args)
                            
                            if name == "create_local_directory":
                                res = self.sandbox.create_local_directory(args.get("relative_path", ""))
                            elif name == "count_directory_files":
                                res = self.sandbox.count_directory_files(args.get("relative_path", ""))
                            elif name == "list_directory_contents":
                                res = await self.sandbox.list_directory_contents(args.get("path", ""), is_remote=is_remote)
                            elif name == "launch_application":
                                res = await self.sandbox.launch_application(args.get("target", ""), args.get("arguments", ""), is_remote=is_remote)
                            elif name == "launch_approved_application":
                                res = await self.sandbox.launch_application(args.get("target_name", ""), args.get("arguments", ""), is_remote=is_remote)
                            elif name == "close_application":
                                res = self.sandbox.close_application(args.get("target", ""))
                            elif name == "search_for_application":
                                res = self.sandbox.search_for_application(args.get("name", ""))
                            elif name == "list_processes":
                                res = self.sandbox.list_processes(args.get("filter_name", ""))
                            elif name == "kill_processes":
                                res = self.sandbox.kill_processes(args.get("pids_or_names", ""))
                            elif name == "delete_local_file":
                                res = await self.sandbox.delete_local_file(args.get("path", ""), is_remote=is_remote)
                            elif name == "control_android_device":
                                action = args.get("action")
                                has_consent = True
                                if action in ["dismiss_alarm", "delete_calendar_event"]:
                                    import uuid
                                    consent_id = str(uuid.uuid4())
                                    
                                    if action == "dismiss_alarm":
                                        h = args.get("alarm_hour")
                                        m = args.get("alarm_minute")
                                        msg = args.get("alarm_message")
                                        desc = "Dismiss/silence alarms on Android device"
                                        if h is not None and h >= 0:
                                            desc += f" set for {h:02d}:{m if m is not None else 0:02d}"
                                        elif msg:
                                            desc += f" matching label '{msg}'"
                                        else:
                                            desc += " (next active alarm)"
                                        pc_msg = f"The AI Agent is requesting permission to dismiss/silence an alarm on your Android device:\n\n{desc}\n\nDo you want to allow this?"
                                        pc_title = "AI Agent Alarm Dismissal Consent"
                                    else:
                                        title = args.get("event_title") or args.get("title") or "Unknown Event"
                                        desc = f"Delete calendar event: '{title}'"
                                        pc_msg = f"The AI Agent is requesting permission to delete a calendar event on your Android device:\n\nEvent Title: {title}\n\nDo you want to allow this?"
                                        pc_title = "AI Agent Calendar Deletion Consent"
                                        
                                    consent_payload = {
                                        "consent_id": consent_id,
                                        "target": action,
                                        "arguments": "",
                                        "app_desc": desc
                                    }
                                    
                                    if is_remote:
                                        from nexuslink.server.ws_server import send_to_all_peers
                                        await send_to_all_peers("launch_consent_request", consent_payload)
                                    
                                    event = asyncio.Event()
                                    consent_status = {"approved": None}
                                    active_consents[consent_id] = (event, consent_status)
                                    
                                    pc_task = None
                                    if not is_remote:
                                        async def run_pc_dialog():
                                            import ctypes
                                            MB_YESNO = 0x04
                                            MB_ICONQUESTION = 0x20
                                            MB_TOPMOST = 0x40000
                                            IDYES = 6
                                            
                                            res = await asyncio.to_thread(ctypes.windll.user32.MessageBoxW, 0, pc_msg, pc_title, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST)
                                            if not event.is_set():
                                                consent_status["approved"] = (res == IDYES)
                                                event.set()
                                                
                                        pc_task = asyncio.create_task(run_pc_dialog())
                                        
                                    try:
                                        await event.wait()
                                    finally:
                                        active_consents.pop(consent_id, None)
                                        if pc_task and not pc_task.done():
                                            import ctypes
                                            hwnd = ctypes.windll.user32.FindWindowW(None, pc_title)
                                            if hwnd:
                                                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                                        if is_remote:
                                            from nexuslink.server.ws_server import send_to_all_peers
                                            await send_to_all_peers("launch_consent_cancel", {"consent_id": consent_id})
                                        
                                    has_consent = bool(consent_status["approved"])
                                    
                                if not has_consent:
                                    res = f"Access Denied: User rejected permission to perform '{action}' on Android device."
                                else:
                                    from nexuslink.server.ws_server import send_to_all_peers
                                    payload_data = {
                                        "action": action,
                                        "package_or_app_name": args.get("package_or_app_name") or args.get("package") or args.get("app_name") or args.get("name"),
                                        "state": args.get("state"),
                                        "stream": args.get("stream"),
                                        "volume_level": args.get("volume_level") or args.get("level") or args.get("volume"),
                                        "alarm_hour": args.get("alarm_hour"),
                                        "alarm_minute": args.get("alarm_minute"),
                                        "alarm_message": args.get("alarm_message"),
                                        "event_title": args.get("event_title"),
                                        "event_description": args.get("event_description"),
                                        "event_start_time": args.get("event_start_time"),
                                        "event_end_time": args.get("event_end_time"),
                                        "ringer_mode": args.get("ringer_mode")
                                    }
                                    await send_to_all_peers("android_action", payload_data)
                                    res = f"Successfully sent remote action request '{action}' to Android device."
                            else:
                                res = f"Security Alert: Model attempted to call unauthorized tool '{name}'"
                            
                            tool_results.append(res)
                            
                            # Append tool response
                            tool_msg = {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": name,
                                "content": str(res)
                            }
                            messages.append(tool_msg)
                            self._conversation_history.append(tool_msg)
                        
                        last_tool_output = "\n".join(tool_results)
                
                # If we hit max iterations, return the last tool's output
                # Trim conversation history
                if len(self._conversation_history) > self._max_history_messages:
                    self._conversation_history = self._conversation_history[-self._max_history_messages:]
                return last_tool_output

        except Exception as e:
            log.exception("Error executing AI command")
            return f"Agent Error: {e}"

agent = OpenRouterAgent(OPENROUTER_API_KEY)

async def handle_nlp_command(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    prompt = msg.payload.get("prompt", "")
    log.info("Received NLP command: %s", prompt)
    
    async def run_agent():
        result_text = await agent.execute_command(prompt, is_remote=True)
        log.info("NLP Result: %s", result_text)
        
        response_msg = NexusMessage(
            type="nlp_response",
            payload={"result": result_text, "prompt": prompt}
        )
        if ws is not None and cipher is not None:
            try:
                await ws.send(cipher.encrypt(response_msg.to_bytes()))
                return
            except Exception as e:
                log.error("Failed to send NLP response over WebSocket: %s", e)
                
        from nexuslink.server import ws_server
        relay = getattr(ws_server, "_firebase_relay", None)
        if relay is not None:
            relay.send_to_phone(response_msg.to_bytes())
            log.info("Sent NLP response via Firebase relay")
        else:
            log.warning("No transport available for NLP response")

    asyncio.create_task(run_agent())


async def handle_launch_consent_response(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    payload = msg.payload
    consent_id = payload.get("consent_id")
    approved = payload.get("approved", False)
    log.info("Received launch consent response for %s: approved=%s", consent_id, approved)
    
    if consent_id in active_consents:
        event, status = active_consents[consent_id]
        status["approved"] = approved
        event.set()


def register(registry: HandlerRegistry) -> None:
    registry.register("nlp_command", handle_nlp_command)
    registry.register("launch_consent_response", handle_launch_consent_response)
