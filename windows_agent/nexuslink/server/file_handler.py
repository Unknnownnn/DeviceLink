import asyncio
import base64
import logging
import os
from pathlib import Path

import aiofiles
from websockets.server import WebSocketServerProtocol

from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry

log = logging.getLogger("nexuslink.file_handler")

# Store active file handles: { file_id: (aiofiles file object, dest_path) }
_active_transfers = {}


def get_downloads_dir() -> Path:
    # Typical Windows downloads directory
    return Path.home() / "Downloads" / "DeviceLink_Downloads"


async def handle_start(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    payload = msg.payload
    file_id = payload.get("file_id")
    file_name = payload.get("file_name")

    if not file_id or not file_name:
        log.error("Invalid file_transfer_start payload.")
        return

    # Security: Prevent directory traversal
    safe_name = os.path.basename(file_name)
    
    downloads_dir = get_downloads_dir()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    dest_path = downloads_dir / safe_name
    
    # Open file asynchronously for binary writing
    try:
        f = await aiofiles.open(dest_path, "wb")
        _active_transfers[file_id] = (f, dest_path)
        log.info("Started receiving file: %s (ID: %s)", safe_name, file_id)
    except Exception as e:
        log.error("Failed to open file for writing: %s", e)


async def handle_chunk(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    payload = msg.payload
    file_id = payload.get("file_id")
    data_b64 = payload.get("data")

    if not file_id or not data_b64:
        log.error("Invalid file_chunk payload.")
        return

    transfer = _active_transfers.get(file_id)
    if not transfer:
        log.error("Received chunk for unknown file_id: %s", file_id)
        return

    f, _ = transfer
    try:
        chunk_bytes = base64.b64decode(data_b64)
        await f.write(chunk_bytes)
    except Exception as e:
        log.error("Failed to write chunk: %s", e)


async def handle_complete(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    payload = msg.payload
    file_id = payload.get("file_id")

    if not file_id:
        log.error("Invalid file_transfer_complete payload.")
        return

    transfer = _active_transfers.pop(file_id, None)
    if not transfer:
        log.error("Received completion for unknown file_id: %s", file_id)
        return

    f, dest_path = transfer
    try:
        await f.close()
        log.info("File transfer complete: %s", dest_path)
    except Exception as e:
        log.error("Failed to close file handle: %s", e)


def register(registry: HandlerRegistry) -> None:
    registry.register("file_transfer_start", handle_start)
    registry.register("file_chunk", handle_chunk)
    registry.register("file_transfer_complete", handle_complete)
