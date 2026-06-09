"""
NexusLink — Clipboard Feature Handler

Handles bidirectional clipboard synchronization.
1. Receives CLIPBOARD_UPDATE messages from the Android app and writes to Windows.
2. Polls the Windows clipboard and sends CLIPBOARD_UPDATE messages to Android.
"""
from __future__ import annotations

import asyncio
import logging
import pyperclip

from nexuslink.models import NexusMessage
from nexuslink.crypto import SessionCipher

log = logging.getLogger("nexuslink.clipboard")

# Keep track of the last known clipboard to prevent echo loops
_last_clipboard_text = ""

# Message Type Constants
MSG_TYPE_CLIPBOARD_UPDATE = "CLIPBOARD_UPDATE"

async def handle_clipboard_update(
    msg: NexusMessage,
    cipher: SessionCipher,
    websocket,
) -> None:
    """Handle incoming clipboard updates from the Android app."""
    global _last_clipboard_text
    
    text = msg.payload.get("text", "")
    if text and text != _last_clipboard_text:
        log.info("Received clipboard update from Android (%d chars)", len(text))
        _last_clipboard_text = text
        try:
            # Note: pyperclip may block briefly depending on the OS mechanism,
            # but on Windows it uses ctypes and is usually very fast.
            pyperclip.copy(text)
            log.debug("Windows clipboard updated.")
        except Exception as exc:
            log.error("Failed to write to Windows clipboard: %s", exc)

def register(registry) -> None:
    """Register this handler with the global registry."""
    registry.register(MSG_TYPE_CLIPBOARD_UPDATE, handle_clipboard_update)

async def clipboard_monitor_task(websocket, cipher: SessionCipher) -> None:
    """
    Background asyncio task that monitors the Windows clipboard for changes
    and sends them to the connected Android device.
    """
    global _last_clipboard_text
    
    log.info("Starting Windows clipboard monitor...")
    
    # Initialize the baseline
    try:
        _last_clipboard_text = pyperclip.paste()
    except Exception:
        pass

    while True:
        try:
            current_text = pyperclip.paste()
            if current_text and current_text != _last_clipboard_text:
                log.info("Windows clipboard changed! Sending to Android (%d chars)", len(current_text))
                _last_clipboard_text = current_text
                
                update_msg = NexusMessage(
                    type=MSG_TYPE_CLIPBOARD_UPDATE,
                    payload={"text": current_text}
                )
                frame = cipher.encrypt(update_msg.to_bytes())
                await websocket.send(frame)
                
        except Exception as exc:
            log.debug("Clipboard poll error (could be locked): %s", exc)
            
        await asyncio.sleep(1.0)  # Poll every 1 second
