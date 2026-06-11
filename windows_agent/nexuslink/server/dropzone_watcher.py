import asyncio
import base64
import logging
import os
import shutil
import uuid
from pathlib import Path

import aiofiles
from websockets.server import WebSocketServerProtocol

from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage

log = logging.getLogger("nexuslink.dropzone")

CHUNK_SIZE = 64 * 1024  # 64 KB


def get_uploads_dir() -> Path:
    d = Path.home() / "Downloads" / "DeviceLink_Uploads"
    d.mkdir(parents=True, exist_ok=True)
    sent_dir = d / "Sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    return d


async def _wait_for_file_ready(filepath: Path) -> bool:
    """Wait until the file size stops changing (e.g. copying has finished)."""
    try:
        prev_size = -1
        for _ in range(10):  # Wait up to 10 seconds
            current_size = filepath.stat().st_size
            if current_size == prev_size and current_size > 0:
                return True
            prev_size = current_size
            await asyncio.sleep(1)
        return False
    except Exception:
        return False


async def dropzone_monitor_task(
    ws: WebSocketServerProtocol, cipher: SessionCipher
) -> None:
    uploads_dir = get_uploads_dir()
    sent_dir = uploads_dir / "Sent"
    
    log.info("Started watching PC DropZone: %s", uploads_dir)

    _dropzone_idle = 0

    while True:
        try:
            # Look for files in the DropZone (only check uploads_dir, not sent_dir)
            found_file = False
            for item in uploads_dir.iterdir():
                if item.is_file() and item.name != ".DS_Store":
                    found_file = True
                    _dropzone_idle = 0
                    # Wait for the file to be completely written to disk
                    ready = await _wait_for_file_ready(item)
                    if not ready:
                        continue
                        
                    file_size = item.stat().st_size
                    file_id = str(uuid.uuid4())
                    
                    log.info("Sending file to Android: %s (%d bytes)", item.name, file_size)

                    # 1. Send start
                    start_msg = NexusMessage(
                        type="file_transfer_start",
                        payload={"file_id": file_id, "file_name": item.name, "file_size": file_size}
                    )
                    await ws.send(cipher.encrypt(start_msg.to_bytes()))

                    # 2. Send chunks
                    seq = 0
                    async with aiofiles.open(item, "rb") as f:
                        while True:
                            chunk = await f.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            
                            b64_data = base64.b64encode(chunk).decode("utf-8")
                            chunk_msg = NexusMessage(
                                type="file_chunk",
                                payload={"file_id": file_id, "sequence": seq, "data": b64_data}
                            )
                            await ws.send(cipher.encrypt(chunk_msg.to_bytes()))
                            seq += 1

                    # 3. Send complete
                    complete_msg = NexusMessage(
                        type="file_transfer_complete",
                        payload={"file_id": file_id}
                    )
                    await ws.send(cipher.encrypt(complete_msg.to_bytes()))
                    log.info("File transfer complete: %s", item.name)

                    # 4. Move to Sent folder
                    dest_path = sent_dir / item.name
                    if dest_path.exists():
                        dest_path.unlink()
                    shutil.move(str(item), str(dest_path))

            if not found_file:
                _dropzone_idle += 1

            # Adaptive back-off: poll fast when files appear, slow when idle
            if _dropzone_idle > 3:
                await asyncio.sleep(5)   # Idle: check every 5s to save disk I/O
            else:
                await asyncio.sleep(2)   # Active: check every 2s
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Dropzone monitor error: %s", e)
            await asyncio.sleep(2)
