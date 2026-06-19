from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
import sys
import threading
from typing import Awaitable, Callable

import pyperclip

from nexuslink.models import NexusMessage
from nexuslink.crypto import SessionCipher

log = logging.getLogger("nexuslink.clipboard")

_last_clipboard_text  = ""
_last_clipboard_image = ""   

MSG_TYPE_CLIPBOARD_UPDATE = "CLIPBOARD_UPDATE"

WM_CLIPBOARDUPDATE = 0x031D
WM_DESTROY        = 0x0002
WM_CLOSE          = 0x0010

CF_UNICODETEXT = 13
CF_DIB         = 8   

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.DefWindowProcW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


def _read_clipboard_text() -> str:
    """Read plain-text from the Windows clipboard via ctypes — no subprocess."""
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    except Exception:
        return ""
    finally:
        user32.CloseClipboard()


def _read_clipboard_image() -> str:
    try:
        from PIL import ImageGrab
        import io
        import base64
        img = ImageGrab.grabclipboard()
        if img is None or not hasattr(img, "save"):
            return ""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        log.debug("Could not read clipboard image: %s", exc)
        return ""


def _read_clipboard_content() -> tuple[str, str]:
    text = _read_clipboard_text()
    if text:
        return text, ""
    image_b64 = _read_clipboard_image()
    return "", image_b64


def _write_clipboard_text(text: str) -> None:
    pyperclip.copy(text)

class _ClipboardListener:
    """
    Listens for WM_CLIPBOARDUPDATE on a hidden Win32 message-only window.
    Pushes True into the asyncio queue whenever the clipboard changes so the
    async consumer can read and forward the new content.
    """

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        self._queue  = queue
        self._loop   = loop
        self._hwnd: int | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="ClipboardHook")
        self._thread.start()

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    def _run(self) -> None:
        """Runs in a dedicated daemon thread — owns the Win32 message pump."""
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_CLIPBOARDUPDATE:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, True)
                return 0
            elif msg in (WM_DESTROY, WM_CLOSE):
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wnd_proc_cb = WNDPROCTYPE(wnd_proc)
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "DeviceLinkClipWatcher"

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style",         ctypes.c_uint),
                ("lpfnWndProc",   WNDPROCTYPE),
                ("cbClsExtra",    ctypes.c_int),
                ("cbWndExtra",    ctypes.c_int),
                ("hInstance",     ctypes.wintypes.HANDLE),
                ("hIcon",         ctypes.wintypes.HANDLE),
                ("hCursor",       ctypes.wintypes.HANDLE),
                ("hbrBackground", ctypes.wintypes.HANDLE),
                ("lpszMenuName",  ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        wc = WNDCLASS()
        wc.lpfnWndProc   = wnd_proc_cb
        wc.hInstance     = hinstance
        wc.lpszClassName = class_name

        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.warning("ClipboardHook: RegisterClassW failed — falling back to polling")
            return

        HWND_MESSAGE = ctypes.wintypes.HWND(-3)
        hwnd = user32.CreateWindowExW(
            0, class_name, "DeviceLinkClipWatcher",
            0, 0, 0, 0, 0,
            HWND_MESSAGE, None, hinstance, None
        )
        if not hwnd:
            log.warning("ClipboardHook: CreateWindowExW failed — falling back to polling")
            return

        self._hwnd = hwnd

        if not user32.AddClipboardFormatListener(hwnd):
            log.warning("ClipboardHook: AddClipboardFormatListener failed — falling back to polling")
            user32.DestroyWindow(hwnd)
            return

        log.info("ClipboardHook: Listening for WM_CLIPBOARDUPDATE on hidden window 0x%X", hwnd)

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.RemoveClipboardFormatListener(hwnd)
        user32.DestroyWindow(hwnd)
        log.info("ClipboardHook: Message pump exited cleanly")


# ── Shared change handler ─────────────────────────────────────────────────────

async def _handle_clipboard_change(
    send_message: Callable[[NexusMessage], Awaitable[None]],
) -> None:
    """
    Read the current clipboard (text or image) and forward it to Android if
    it differs from the last value that was sent.
    """
    global _last_clipboard_text, _last_clipboard_image

    text, image_b64 = _read_clipboard_content()

    if text and text != _last_clipboard_text:
        _last_clipboard_text  = text
        _last_clipboard_image = ""
        log.info("Clipboard changed (text) → sending to Android (%d chars)", len(text))
        await send_message(NexusMessage(
            type=MSG_TYPE_CLIPBOARD_UPDATE,
            payload={"text": text}
        ))

    elif image_b64 and image_b64 != _last_clipboard_image:
        _last_clipboard_image = image_b64
        _last_clipboard_text  = ""
        log.info(
            "Clipboard changed (image) → sending to Android (%d bytes b64)",
            len(image_b64),
        )
        await send_message(NexusMessage(
            type=MSG_TYPE_CLIPBOARD_UPDATE,
            payload={"image": image_b64}
        ))


# ── Main async monitor task ───────────────────────────────────────────────────

async def clipboard_monitor_task(send_message: Callable[[NexusMessage], Awaitable[None]]) -> None:

    global _last_clipboard_text, _last_clipboard_image

    log.info("Starting Windows clipboard monitor (event-driven mode)...")

    try:
        _last_clipboard_text = _read_clipboard_text() or pyperclip.paste()
    except Exception:
        pass

    if sys.platform == "win32":
        loop = asyncio.get_event_loop()
        clip_queue: asyncio.Queue[bool] = asyncio.Queue()
        listener = _ClipboardListener(clip_queue, loop)
        listener.start()

        await asyncio.sleep(0.3)

        if listener._hwnd:
            log.info("Clipboard event hook active — zero idle CPU usage.")
            try:
                while True:
                    await clip_queue.get()
                    # Brief pause so the clipboard owner can finish writing
                    await asyncio.sleep(0.05)
                    await _handle_clipboard_change(send_message)
            except asyncio.CancelledError:
                listener.stop()
                raise
            except Exception as exc:
                log.error("Clipboard event loop error: %s — falling back to polling", exc)
                listener.stop()
        else:
            log.warning("Clipboard hook unavailable — using polling fallback")

    log.info("Clipboard monitor: using polling fallback (2.5 s interval)")
    _idle = 0
    while True:
        try:
            await _handle_clipboard_change(send_message)
            _idle = 0
        except Exception as exc:
            log.debug("Clipboard poll error: %s", exc)
            _idle += 1

        await asyncio.sleep(0.5 if _idle < 3 else 2.5)


# ── Incoming handler (Android → Windows) ─────────────────────────────────────

async def handle_clipboard_update(
    msg: NexusMessage,
    cipher: SessionCipher,
    websocket,
) -> None:
    """Handle incoming clipboard updates from the Android app (text only for now)."""
    global _last_clipboard_text

    text = msg.payload.get("text", "")
    if text and text != _last_clipboard_text:
        log.info("Received text clipboard update from Android (%d chars)", len(text))
        _last_clipboard_text = text
        try:
            _write_clipboard_text(text)
            log.debug("Windows clipboard updated from Android.")
        except Exception as exc:
            log.error("Failed to write to Windows clipboard: %s", exc)


def register(registry) -> None:
    """Register this handler with the global registry."""
    registry.register(MSG_TYPE_CLIPBOARD_UPDATE, handle_clipboard_update)
