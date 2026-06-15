"""
NexusLink — Ping/Pong Feature Handler

Responds to encrypted 'ping' messages with a 'pong' message,
verifying the end-to-end encrypted channel is working correctly.
"""
from __future__ import annotations

import logging

from nexuslink.models import NexusMessage, MsgType
from nexuslink.crypto import SessionCipher

log = logging.getLogger("nexuslink.ping")


async def handle_ping(
    msg: NexusMessage,
    cipher: SessionCipher,
    websocket,
) -> None:
    """
    Echo back a 'pong' in response to every 'ping'.
    The pong payload mirrors back whatever the client sent, plus a
    server-side timestamp for round-trip measurement.
    """
    import time

    log.info("PING received [id=%s] payload=%s", msg.id, msg.payload)

    pong = NexusMessage(
        type=MsgType.PONG,
        payload={
            "echo": msg.payload,
            "server_ts": time.time(),
        },
    )
    if cipher and websocket:
        frame = cipher.encrypt(pong.to_bytes())
        await websocket.send(frame)
        log.info("PONG sent via WebSocket/UDP [ref=%s]", msg.id)
    else:
        import nexuslink.server.ws_server as ws_server
        relay = getattr(ws_server, "_firebase_relay", None)
        if relay:
            relay.send_to_phone(pong.to_bytes())
            log.info("PONG sent via Firebase [ref=%s]", msg.id)


def register(registry) -> None:
    """Register this handler with the global registry."""
    registry.register(MsgType.PING, handle_ping)
