from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import ctypes
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
from . import ping_handler
from . import clipboard_handler
from . import file_handler
from . import dropzone_watcher
from . import agent_orchestrator
from . import power_handler
from . import call_handler

log = logging.getLogger("nexuslink.ws_server")

ping_handler.register(registry)
clipboard_handler.register(registry)
file_handler.register(registry)
agent_orchestrator.register(registry)
power_handler.register(registry)
call_handler.register(registry)

active_peers = set()
active_sessions = []
_loop = None

def get_active_peers():
    return list(active_peers)

def extract_shortcut_icon(target: str, item_type: str = "app", size: int = 64) -> str:
    """
    Extracts the Windows icon for a given target path, short name, or steam game ID,
    returning it as a base64 encoded PNG.
    """
    # 1. Clean and resolve target path
    target_clean = target.strip()
    
    if item_type == "steam":
        if "rungameid/" in target_clean:
            target_clean = target_clean.split("rungameid/")[-1]
    
    # Strip quotes
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

    # 2. Extract icon using ctypes
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

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ("hIcon", ctypes.c_void_p),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", ctypes.c_uint32),
            ("szDisplayName", ctypes.c_wchar * 260),
            ("szTypeName", ctypes.c_wchar * 80)
        ]

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

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

    shfi = SHFILEINFOW()
    SHGFI_ICON = 0x000000100
    SHGFI_LARGEICON = 0x000000000
    
    res = shell32.SHGetFileInfoW(
        file_path,
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

def sync_shortcuts_to_active_peers() -> None:
    from nexuslink.settings_manager import SettingsManager
    settings = SettingsManager()
    shortcuts = settings.get_deck_shortcuts()
    shortcuts_with_icons = []
    for s in shortcuts:
        s_copy = s.copy()
        icon_b64 = extract_shortcut_icon(s.get("target", ""), s.get("type", "app"))
        if icon_b64:
            s_copy["icon"] = icon_b64
        shortcuts_with_icons.append(s_copy)
    send_message_to_all_peers_sync("sync_shortcuts", {"shortcuts": shortcuts_with_icons})

async def send_to_all_peers(msg_type: str, payload: dict) -> None:
    from nexuslink.models import NexusMessage
    msg = NexusMessage(type=msg_type, payload=payload)
    data = msg.to_bytes()
    for ws, cipher in list(active_sessions):
        try:
            frame = cipher.encrypt(data)
            await ws.send(frame)
            log.info("Sent message '%s' to peer %s", msg_type, ws.remote_address)
        except Exception as exc:
            log.error("Failed to send message to peer %s: %s", ws.remote_address, exc)

def send_message_to_all_peers_sync(msg_type: str, payload: dict) -> None:
    global _loop
    if _loop is None:
        log.warning("No running server event loop found to send message.")
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


    async def start(self) -> None:
        global _loop
        _loop = asyncio.get_running_loop()
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

            from nexuslink.settings_manager import SettingsManager
            settings = SettingsManager()
            shortcuts = settings.get_deck_shortcuts()
            shortcuts_with_icons = []
            for s in shortcuts:
                s_copy = s.copy()
                icon_b64 = extract_shortcut_icon(s.get("target", ""), s.get("type", "app"))
                if icon_b64:
                    s_copy["icon"] = icon_b64
                shortcuts_with_icons.append(s_copy)

            shortcuts_msg = NexusMessage(
                type="sync_shortcuts",
                payload={"shortcuts": shortcuts_with_icons}
            )
            await websocket.send(cipher.encrypt(shortcuts_msg.to_bytes()))

            await self._run_session(websocket, cipher)

        except websockets.ConnectionClosedOK:
            log.info("Connection closed cleanly by %s", peer)
        except websockets.ConnectionClosedError as exc:
            log.warning("Connection closed with error from %s: %s", peer, exc)
        except Exception as exc:
            log.exception("Unexpected error handling %s: %s", peer, exc)
        finally:
            active_peers.discard(peer)
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

        log.info("HELLO received from client (ed25519: %s…)", client_ed25519_b64[:12])

        hs = HandshakeManager()
        my_x25519_pub_raw = _b64url_decode(hs.public_key_b64)
        client_x25519_raw = _b64url_decode(client_x25519_b64)
        transcript_to_sign = my_x25519_pub_raw + client_x25519_raw
        signature_raw = self._identity.sign(transcript_to_sign)
        signature_b64 = base64.urlsafe_b64encode(signature_raw).rstrip(b"=").decode()

        hello_ack = NexusMessage(
            type=MsgType.HELLO_ACK,
            payload={
                "x25519_public_key": hs.public_key_b64,
                "ed25519_public_key": self._identity.public_key_b64,
                "signature": signature_b64,
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
        monitor_task = asyncio.create_task(clipboard_handler.clipboard_monitor_task(ws, cipher))
        dropzone_task = asyncio.create_task(dropzone_watcher.dropzone_monitor_task(ws, cipher))
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
            dropzone_task.cancel()

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
