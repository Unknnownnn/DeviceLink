from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import ctypes
import time
from io import BytesIO
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol
from PIL import Image

from config import WS_HOST, WS_PORT
from nexuslink.crypto import HandshakeManager, SessionCipher
from nexuslink.identity import IdentityManager
from nexuslink.models import NexusMessage, MsgType
from .handlers import registry
from . import clipboard_handler
from . import file_handler
from . import agent_orchestrator
from . import power_handler
from . import call_handler
from . import ping_handler
from . import phone_status_handler
from .firebase_relay import FirebaseRelay

_firebase_relay: Optional[FirebaseRelay] = None

log = logging.getLogger("nexuslink.ws_server")

clipboard_handler.register(registry)
file_handler.register(registry)
agent_orchestrator.register(registry)
power_handler.register(registry)
call_handler.register(registry)
ping_handler.register(registry)
phone_status_handler.register(registry)

active_peers = set()
active_sessions = []
_loop = None
_cloud_clipboard_task = None
_connected_device_name = "Android Device"

def get_connected_device_name() -> str:
    global _connected_device_name
    return _connected_device_name

log_subscribers = set()
firebase_wants_logs = False
last_firebase_activity = 0
cloud_relay_active = False

def get_firebase_status():
    global last_firebase_activity
    return last_firebase_activity

def get_cloud_relay_active():
    global cloud_relay_active
    if cloud_relay_active:
        if time.time() - last_firebase_activity > 15.0:
            log.info("Cloud relay timed out (no messages received for 15 seconds)")
            if _loop:
                _loop.call_soon_threadsafe(_set_cloud_relay_active, False)
            else:
                _set_cloud_relay_active(False)
    return cloud_relay_active

def _set_cloud_relay_active(active: bool) -> None:
    global cloud_relay_active, last_firebase_activity, firebase_wants_logs, _firebase_relay, _cloud_clipboard_task
    if cloud_relay_active == active:
        return
    cloud_relay_active = active
    if active:
        last_firebase_activity = time.time()
        if _firebase_relay:
            _firebase_relay.start_heartbeat()
        if _cloud_clipboard_task is None or _cloud_clipboard_task.done():
            async def _send_clipboard_update(msg: NexusMessage) -> None:
                if _firebase_relay:
                    _firebase_relay.send_to_phone(msg.to_bytes())

            _cloud_clipboard_task = asyncio.create_task(
                clipboard_handler.clipboard_monitor_task(_send_clipboard_update)
            )
    else:
        firebase_wants_logs = False
        if _firebase_relay:
            _firebase_relay.stop_heartbeat()
        if _cloud_clipboard_task is not None:
            _cloud_clipboard_task.cancel()
            _cloud_clipboard_task = None
        # Notify GUI to refresh immediately
        from .handlers import get_app_instance
        app = get_app_instance()
        if app:
            app.after(0, lambda: app.handle_cloud_relay_disconnect())


async def handle_subscribe_logs(msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol) -> None:
    global firebase_wants_logs
    enable = msg.payload.get("enable", False)
    if enable:
        if ws:
            log_subscribers.add(ws)
            log.info("Peer %s subscribed to logs", ws.remote_address)
        else:
            firebase_wants_logs = True
            log.info("Firebase client subscribed to logs")
    else:
        if ws:
            log_subscribers.discard(ws)
            log.info("Peer %s unsubscribed from logs", ws.remote_address)
        else:
            firebase_wants_logs = False
            log.info("Firebase client unsubscribed from logs")

registry.register("subscribe_logs", handle_subscribe_logs)

async def handle_request_sync(msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol) -> None:
    if cipher and ws:
        asyncio.create_task(send_shortcuts_and_icons(ws, cipher))
        await ws.send(cipher.encrypt(NexusMessage("request_contacts", {}).to_bytes()))
        await ws.send(cipher.encrypt(NexusMessage("request_phone_status", {}).to_bytes()))
    elif _firebase_relay:
        asyncio.create_task(send_shortcuts_and_icons(None, None))
        _firebase_relay.send_to_phone(NexusMessage("request_contacts", {}).to_bytes())
        _firebase_relay.send_to_phone(NexusMessage("request_phone_status", {}).to_bytes())

async def handle_cloud_disconnect(msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol) -> None:
    log.info("Cloud relay disconnect received from phone.")
    _set_cloud_relay_active(False)
    from .handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_cloud_relay_disconnect())

async def handle_udp_disconnect(msg: NexusMessage, cipher: SessionCipher, ws) -> None:
    log.info("UDP disconnect received from phone.")
    import nexuslink.server.udp_server as udp_server
    udp_server.active_udp_session = None

registry.register("request_sync", handle_request_sync)
registry.register("cloud_disconnect", handle_cloud_disconnect)
registry.register("udp_disconnect", handle_udp_disconnect)

def get_active_peers():
    return list(active_peers)

def fetch_website_favicon(url: str, size: int = 64) -> str:
    """
    Downloads the favicon for a website (using Google's favicon service)
    and returns it as a base64 encoded PNG string.
    """
    import urllib.request
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc or parsed.path
        if not domain:
            return ""
        favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz={size}"
        req = urllib.request.Request(
            favicon_url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=3.0) as response:
            data = response.read()
            return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        log.warning("Failed to fetch favicon for %s: %s", url, e)
        return ""

def extract_shortcut_icon(target: str, item_type: str = "app", size: int = 64) -> str:
    """
    Extracts the Windows icon for a given target path, short name, or steam game ID,
    returning it as a base64 encoded PNG. Supports extracting UWP (Store) app icons.
    """
    # 1. Clean and resolve target path
    target_clean = target.strip()

    if item_type == "url":
        return fetch_website_favicon(target_clean, size)
    
    if item_type == "steam":
        if "rungameid/" in target_clean:
            target_clean = target_clean.split("rungameid/")[-1]

    # Declare user32, gdi32, shell32 early
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

    # Common structures
    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ("hIcon", ctypes.c_void_p),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", ctypes.c_uint32),
            ("szDisplayName", ctypes.c_wchar * 260),
            ("szTypeName", ctypes.c_wchar * 80)
        ]

    # Configure Shell32 API signatures once to avoid global type pollution in ctypes
    shell32.SHParseDisplayName.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong)
    ]
    shell32.SHParseDisplayName.restype = ctypes.c_long

    shell32.SHGetFileInfoW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,  
        ctypes.c_uint,
        ctypes.c_uint
    ]
    shell32.SHGetFileInfoW.restype = ctypes.c_void_p

    hicon = None

    # Handle UWP (Windows Store) apps using virtual shell:AppsFolder Parsing
    if target_clean.lower().startswith("shell:"):
        com_initialized = False
        try:
            ole32 = ctypes.windll.ole32
            # Explicitly initialize COM on the calling thread if not already initialized
            hr_init = ole32.CoInitialize(None)
            if hr_init >= 0:
                com_initialized = True

            pidl = ctypes.c_void_p()
            sfgao = ctypes.c_ulong(0)
            hr = shell32.SHParseDisplayName(target_clean, None, ctypes.byref(pidl), 0, ctypes.byref(sfgao))
            if hr == 0 and pidl.value:
                shfi_pidl = SHFILEINFOW()
                SHGFI_PIDL = 0x000000008
                SHGFI_ICON = 0x000000100
                SHGFI_LARGEICON = 0x000000000

                shell32.SHGetFileInfoW(
                    pidl,
                    0,
                    ctypes.byref(shfi_pidl),
                    ctypes.sizeof(shfi_pidl),
                    SHGFI_PIDL | SHGFI_ICON | SHGFI_LARGEICON
                )
                ole32.CoTaskMemFree(pidl)
                if shfi_pidl.hIcon:
                    hicon = shfi_pidl.hIcon
        except Exception as e:
            log.warning("Failed to extract UWP shell PIDL icon for %s: %s", target_clean, e)
        finally:
            if com_initialized:
                try:
                    ole32.CoUninitialize()
                except Exception:
                    pass

    if not hicon:
        # Standard resolving for regular files, executable paths, or classic app shortcuts
        if target_clean.startswith('"'):
            idx = target_clean.find('"', 1)
            if idx != -1:
                target_clean = target_clean[1:idx]
        else:
            # Strip command line arguments from the end of executable path
            if ".exe" in target_clean.lower():
                parts = target_clean.split()
                for i in range(len(parts)):
                    joined = " ".join(parts[:i+1])
                    if joined.lower().endswith(".exe"):
                        target_clean = joined
                        break

        file_path = ""
        if item_type == "steam":
            # Resolve Steam game icon from Steam's cache directory
            for steam_dir in [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]:
                ico_path = os.path.join(steam_dir, "steam", "games", f"{target_clean}.ico")
                if os.path.exists(ico_path):
                    file_path = ico_path
                    break
            if not file_path:
                # Fall back to steam.exe icon
                for steam_dir in [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]:
                    exe_path = os.path.join(steam_dir, "steam.exe")
                    if os.path.exists(exe_path):
                        file_path = exe_path
                        break
        else:
            # It's a regular app or file shortcut
            if os.path.isabs(target_clean) and os.path.exists(target_clean):
                file_path = target_clean
            else:
                # Check system PATH
                resolved = shutil.which(target_clean)
                if resolved and os.path.exists(resolved):
                    file_path = resolved
                else:
                    # Try common locations
                    windir = os.environ.get("WINDIR", "C:\\Windows")
                    for path in [
                        os.path.join(windir, target_clean),
                        os.path.join(windir, "System32", target_clean),
                    ]:
                        if os.path.exists(path):
                            file_path = path
                            break

        if not file_path or not os.path.exists(file_path):
            return ""

        # Normalize path to backslashes for Windows API
        file_path = os.path.normpath(file_path)

        shfi = SHFILEINFOW()
        SHGFI_ICON = 0x000000100
        SHGFI_LARGEICON = 0x000000000
        
        res = shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(file_path),
            0,
            ctypes.byref(shfi),
            ctypes.sizeof(shfi),
            SHGFI_ICON | SHGFI_LARGEICON
        )
        
        if not res or not shfi.hIcon:
            # Fallback to ExtractIconExW if SHGetFileInfoW failed (or returned no icon)
            phiconLarge = ctypes.c_void_p()
            phiconSmall = ctypes.c_void_p()
            num_extracted = shell32.ExtractIconExW(
                file_path,
                0,
                ctypes.byref(phiconLarge),
                ctypes.byref(phiconSmall),
                1
            )
            if num_extracted > 0 and phiconLarge:
                hicon = phiconLarge
            elif num_extracted > 0 and phiconSmall:
                hicon = phiconSmall
            else:
                return ""
        else:
            hicon = shfi.hIcon
    
    # 2. Proceed to draw the hicon to a bitmap and encode to Base64 PNG
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_int16),
            ("biBitCount", ctypes.c_int16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", ctypes.c_uint32 * 3)
        ]

    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    user32.DrawIconEx.restype = ctypes.c_bool
    user32.DrawIconEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint
    ]

    user32.DestroyIcon.restype = ctypes.c_bool
    user32.DestroyIcon.argtypes = [ctypes.c_void_p]

    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]

    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    gdi32.DeleteObject.restype = ctypes.c_bool
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]

    gdi32.DeleteDC.restype = ctypes.c_bool
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint
    ]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p

    try:
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        
        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        
        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_mem,
            ctypes.byref(bmi),
            0,
            ctypes.byref(bits_ptr),
            None,
            0
        )
        
        user32.ReleaseDC(None, hdc_screen)
        
        if not hbmp or not bits_ptr:
            return ""
            
        hbmp_old = gdi32.SelectObject(hdc_mem, hbmp)
        user32.DrawIconEx(hdc_mem, 0, 0, hicon, size, size, 0, None, 0x0003)
        
        buf_size = size * size * 4
        buf_data = ctypes.string_at(bits_ptr, buf_size)
        
        img = Image.frombuffer("RGBA", (size, size), buf_data, "raw", "BGRA", 0, 1)
        
        gdi32.SelectObject(hdc_mem, hbmp_old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception:
        return ""
    finally:
        user32.DestroyIcon(hicon)

async def send_shortcuts_and_icons(ws=None, cipher=None) -> None:
    from nexuslink.settings_manager import SettingsManager
    from nexuslink.models import NexusMessage
    settings = SettingsManager()
    shortcuts = settings.get_deck_shortcuts()
    
    # 1. Populate apps first without large base64 icons to display UI instantly
    shortcuts_no_icons = []
    for s in shortcuts:
        s_copy = s.copy()
        s_copy["icon"] = ""
        shortcuts_no_icons.append(s_copy)
        
    shortcuts_msg = NexusMessage(
        type="sync_shortcuts",
        payload={"shortcuts": shortcuts_no_icons}
    )
    
    if ws is not None:
        if cipher is not None:
            await ws.send(cipher.encrypt(shortcuts_msg.to_bytes()))
    else:
        await send_to_all_peers("sync_shortcuts", {"shortcuts": shortcuts_no_icons})
        
    # 2. Extract and send icons one by one asynchronously to pace network traffic
    for s in shortcuts:
        icon_b64 = s.get("custom_icon")
        if not icon_b64:
            icon_b64 = extract_shortcut_icon(s.get("target", ""), s.get("type", "app"))
        if icon_b64:
            # Short sleep to prevent network congestion/dropped packets over UDP
            await asyncio.sleep(0.12)
            icon_msg = NexusMessage(
                type="sync_shortcut_icon",
                payload={"id": s.get("id", ""), "icon": icon_b64}
            )
            if ws is not None:
                if cipher is not None:
                    await ws.send(cipher.encrypt(icon_msg.to_bytes()))
            else:
                await send_to_all_peers("sync_shortcut_icon", {"id": s.get("id", ""), "icon": icon_b64})

def sync_shortcuts_to_active_peers() -> None:
    if _loop:
        asyncio.run_coroutine_threadsafe(send_shortcuts_and_icons(None, None), _loop)

async def send_to_all_peers(msg_type: str, payload: dict) -> None:
    from nexuslink.models import NexusMessage
    msg = NexusMessage(type=msg_type, payload=payload)
    data = msg.to_bytes()
    sent_via_channel = False
    
    # 1. Try WebSocket
    for ws, cipher in list(active_sessions):
        if msg_type == "pc_log" and ws not in log_subscribers:
            continue
        try:
            frame = cipher.encrypt(data)
            await ws.send(frame)
            log.info("Sent message '%s' to peer %s", msg_type, ws.remote_address)
            sent_via_channel = True
        except Exception as exc:
            log.error("Failed to send message to peer %s: %s", ws.remote_address, exc)
            
    # 2. Try UDP connection
    import nexuslink.server.udp_server as udp_server
    active_udp = udp_server.get_active_udp_session()
    if not sent_via_channel and active_udp and msg_type != "pc_log":
        try:
            cipher = active_udp["cipher"]
            frame = cipher.encrypt(data)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: active_udp["socket"].sendto(frame, active_udp["addr"]))
            log.info("Sent message '%s' via UDP to %s", msg_type, active_udp["addr"])
            sent_via_channel = True
        except Exception as exc:
            log.error("Failed to send message to peer via UDP: %s", exc)
            
    # 3. Fallback to Firebase Relay
    if not sent_via_channel and _firebase_relay:
        if msg_type == "pc_log" and not firebase_wants_logs:
            pass # Don't send logs if not subscribed
        else:
            _firebase_relay.send_to_phone(data)
            log.info("Sent message '%s' via Firebase Fallback", msg_type)

def send_message_to_all_peers_sync(msg_type: str, payload: dict) -> None:
    global _loop
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(send_to_all_peers(msg_type, payload), _loop)


class NexusLinkServer:
    """
    asyncio WebSocket server that handles one or more concurrent peer
    connections.  Each connection goes through the handshake independently.
    """

    def __init__(
        self,
        identity: IdentityManager,
        host: str = WS_HOST,
        port: int = WS_PORT,
    ) -> None:
        self._identity = identity
        self._host = host
        self._port = port
        self._server: Optional[websockets.WebSocketServer] = None
        
        global _firebase_relay
        db_url = "https://devicelink-d4665-default-rtdb.asia-southeast1.firebasedatabase.app/"
        _firebase_relay = FirebaseRelay(db_url, identity.fingerprint, self._on_firebase_message)
        _firebase_relay.start_heartbeat()

        import nexuslink.server.udp_server as udp_server
        udp_server._udp_manager = udp_server.UdpServerManager(
            self._port, identity, on_session_established=self._on_udp_session_established
        )

    def _handle_stun_initiate(self, payload):
        import nexuslink.server.udp_server as udp_server
        import threading
        manager = udp_server._udp_manager
        if not manager:
            log.error("UDP Server Manager not initialized!")
            return
            
        local_ip = manager.get_local_ip()
        local_port = manager.port
        
        log.info("Querying STUN server to respond to client...")
        stun_res = manager.query_stun()
        if stun_res:
            public_ip, public_port = stun_res
            log.info("STUN Query success: %s:%d (Local: %s:%d)", public_ip, public_port, local_ip, local_port)
        else:
            public_ip = local_ip
            public_port = local_port
            log.warning("STUN Query failed. Using local details as fallback.")
            
        from nexuslink.models import NexusMessage
        resp_msg = NexusMessage(
            type="stun_response",
            payload={
                "local_ip": local_ip,
                "local_port": local_port,
                "public_ip": public_ip,
                "public_port": public_port
            }
        )
        if _firebase_relay:
            _firebase_relay.send_to_phone(resp_msg.to_bytes())
            log.info("Sent stun_response to client via Firebase")
            
        manager.start_hole_punching(payload)

    def _on_udp_session_established(self, addr, cipher):
        log.info("UDP Session active with %s. Sending sync requests...", addr)
        import nexuslink.server.udp_server as udp_server
        wrapper = udp_server.UdpSessionWrapper(udp_server._udp_manager.sock, addr, cipher)
        if _loop:
            asyncio.run_coroutine_threadsafe(send_shortcuts_and_icons(wrapper, cipher), _loop)
            asyncio.run_coroutine_threadsafe(wrapper.send(cipher.encrypt(NexusMessage("request_contacts", {}).to_bytes())), _loop)
            asyncio.run_coroutine_threadsafe(wrapper.send(cipher.encrypt(NexusMessage("request_phone_status", {}).to_bytes())), _loop)

    def _on_firebase_message(self, plaintext: bytes):
        global last_firebase_activity
        last_firebase_activity = time.time()
        try:
            from nexuslink.models import NexusMessage
            msg = NexusMessage.from_bytes(plaintext)
            log.debug("→ (Firebase) [%s] %s", msg.type, msg.id)

            if msg.type == "stun_initiate":
                import threading
                threading.Thread(target=self._handle_stun_initiate, args=(msg.payload,), daemon=True).start()
                return

            if msg.type == "request_sync":
                device_name = msg.payload.get("device_name", "Android Device")
                global _connected_device_name
                _connected_device_name = device_name
                if _loop:
                    _loop.call_soon_threadsafe(_set_cloud_relay_active, True)
            
            if msg.type == "request_sync":
                print(f"[Server] ← Firebase Cloud Relay connection established with {device_name}!")
                print("[Server] ✓ Secure session active via Cloud")
                
            if _loop:
                asyncio.run_coroutine_threadsafe(registry.dispatch(msg, None, None), _loop)
        except Exception as e:
            log.error("Failed to process firebase msg: %s", e)

    async def start(self) -> None:
        global _loop
        _loop = asyncio.get_running_loop()
        import nexuslink.server.udp_server as udp_server
        udp_server._loop = _loop
        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            max_size=10 * 1024 * 1024,
        )
        log.info(
            "NexusLink WebSocket server listening on ws://%s:%d",
            self._host, self._port,
        )
        print(f"[Server] WebSocket server ready on ws://0.0.0.0:{self._port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("WebSocket server stopped.")
        import nexuslink.server.udp_server as udp_server
        if udp_server._udp_manager:
            udp_server._udp_manager.stop()


    async def _handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str = "/",
    ) -> None:
        peer = websocket.remote_address
        log.info("New connection from %s", peer)
        print(f"[Server] ← Connection from {peer}")

        try:
            cipher = await self._do_handshake(websocket)
            if cipher is None:
                log.warning("Handshake failed for %s — closing.", peer)
                await websocket.close(1008, "Handshake failed")
                return

            log.info("Secure session established with %s", websocket.remote_address)
            print(f"[Server] ✓ Secure session with {websocket.remote_address}")

            active_peers.add(peer)
            active_sessions.append((websocket, cipher))

            asyncio.create_task(send_shortcuts_and_icons(websocket, cipher))

            # Request contacts and status from the phone
            contacts_req = NexusMessage(
                type="request_contacts",
                payload={}
            )
            await websocket.send(cipher.encrypt(contacts_req.to_bytes()))

            status_req = NexusMessage(
                type="request_phone_status",
                payload={}
            )
            await websocket.send(cipher.encrypt(status_req.to_bytes()))

            await self._run_session(websocket, cipher)

        except websockets.ConnectionClosedOK:
            log.info("Connection closed cleanly by %s", peer)
        except websockets.ConnectionClosedError as exc:
            log.warning("Connection closed with error from %s: %s", peer, exc)
        except Exception as exc:
            log.exception("Unexpected error handling %s: %s", peer, exc)
        finally:
            active_peers.discard(peer)
            log_subscribers.discard(websocket)
            _set_cloud_relay_active(False)
            for item in list(active_sessions):
                if item[0] == websocket:
                    try:
                        active_sessions.remove(item)
                    except ValueError:
                        pass
            log.info("Peer disconnected: %s", peer)
            print(f"[Server] ✗ Peer disconnected: {peer}")


    async def _do_handshake(
        self,
        ws: WebSocketServerProtocol,
    ) -> Optional[SessionCipher]:
        """
        Execute the 3-message X25519 + Ed25519 handshake.
        Returns a SessionCipher on success, None on failure.
        """
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
        except asyncio.TimeoutError:
            log.warning("Handshake timeout waiting for HELLO")
            return None

        try:
            hello = NexusMessage.from_bytes(
                raw if isinstance(raw, bytes) else raw.encode()
            )
        except Exception as exc:
            log.warning("Invalid HELLO message: %s", exc)
            return None

        if hello.type != MsgType.HELLO:
            log.warning("Expected HELLO, got: %s", hello.type)
            return None

        client_x25519_b64: str = hello.payload["x25519_public_key"]
        client_ed25519_b64: str = hello.payload["ed25519_public_key"]
        device_name: str = hello.payload.get("device_name", "Android Device")
        global _connected_device_name
        _connected_device_name = device_name

        log.info("HELLO received from client (ed25519: %s…)", client_ed25519_b64[:12])

        hs = HandshakeManager()
        my_x25519_pub_raw = _b64url_decode(hs.public_key_b64)
        client_x25519_raw = _b64url_decode(client_x25519_b64)
        transcript_to_sign = my_x25519_pub_raw + client_x25519_raw
        signature_raw = self._identity.sign(transcript_to_sign)
        signature_b64 = base64.urlsafe_b64encode(signature_raw).rstrip(b"=").decode()

        import socket
        hello_ack = NexusMessage(
            type=MsgType.HELLO_ACK,
            payload={
                "x25519_public_key": hs.public_key_b64,
                "ed25519_public_key": self._identity.public_key_b64,
                "signature": signature_b64,
                "device_name": socket.gethostname(),
            },
        )
        await ws.send(hello_ack.to_bytes())
        log.info("HELLO_ACK sent.")

        try:
            raw2 = await asyncio.wait_for(ws.recv(), timeout=15.0)
        except asyncio.TimeoutError:
            log.warning("Handshake timeout waiting for HELLO_CONFIRM")
            return None

        try:
            confirm = NexusMessage.from_bytes(
                raw2 if isinstance(raw2, bytes) else raw2.encode()
            )
        except Exception as exc:
            log.warning("Invalid HELLO_CONFIRM: %s", exc)
            return None

        if confirm.type != MsgType.HELLO_CONFIRM:
            log.warning("Expected HELLO_CONFIRM, got: %s", confirm.type)
            return None

        client_sig_raw = _b64url_decode(confirm.payload["signature"])
        transcript_expected = client_x25519_raw + my_x25519_pub_raw
        client_ed25519_raw = _b64url_decode(client_ed25519_b64)

        if not _verify_ed25519(client_ed25519_raw, transcript_expected, client_sig_raw):
            log.warning("HELLO_CONFIRM signature verification FAILED")
            return None

        log.info("HELLO_CONFIRM signature verified")

        session_key = hs.derive_session_key(client_x25519_b64)
        log.info("Session key derived (32 bytes)")
        return SessionCipher(session_key)


    async def _run_session(
        self,
        ws: WebSocketServerProtocol,
        cipher: SessionCipher,
    ) -> None:
        """Receive and dispatch encrypted messages indefinitely."""
        async def send_clipboard_update(msg: NexusMessage) -> None:
            frame = cipher.encrypt(msg.to_bytes())
            await ws.send(frame)

        monitor_task = asyncio.create_task(clipboard_handler.clipboard_monitor_task(send_clipboard_update))
        try:
            async for frame in ws:
                if isinstance(frame, str):
                    log.warning("Received unexpected text frame — ignoring.")
                    continue
                try:
                    plaintext = cipher.decrypt(frame)
                    msg = NexusMessage.from_bytes(plaintext)
                    log.debug("→ [%s] %s", msg.type, msg.id)
                    await registry.dispatch(msg, cipher, ws)
                except Exception as exc:
                    log.error("Failed to process frame: %s", exc)
        finally:
            monitor_task.cancel()

def _b64url_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _verify_ed25519(pub_key_raw: bytes, message: bytes, signature: bytes) -> bool:
    from nacl.signing import VerifyKey
    try:
        VerifyKey(pub_key_raw).verify(message, signature)
        return True
    except Exception:
        return False
