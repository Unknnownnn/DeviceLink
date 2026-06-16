"""
NexusLink — Plugin-style Message Handler Registry

Each feature registers itself with the global `HandlerRegistry` by calling
`registry.register(msg_type, handler_fn)`.  The WebSocket server dispatches
every decrypted message to the appropriate handler.

Handler signature::

    async def my_handler(
        msg: NexusMessage,
        cipher: SessionCipher,
        websocket: websockets.WebSocketServerProtocol,
    ) -> None:
        ...
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict, Optional

from nexuslink.models import NexusMessage
from nexuslink.crypto import SessionCipher

log = logging.getLogger("nexuslink.handlers")

_app_instance = None

def register_app_instance(app):
    global _app_instance
    _app_instance = app
    log.info("Registered active GUI app instance: %s", app)

def get_app_instance():
    return _app_instance

HandlerFn = Callable[
    [NexusMessage, SessionCipher, object],  
    Awaitable[None],
]


class HandlerRegistry:
    """
    A simple dictionary-backed registry mapping message type strings to
    async handler coroutines.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, HandlerFn] = {}

    def register(self, msg_type: str, handler: HandlerFn) -> None:
        """Register *handler* for messages of *msg_type*."""
        self._handlers[msg_type] = handler
        log.debug("Registered handler for message type: %s", msg_type)

    def get(self, msg_type: str) -> Optional[HandlerFn]:
        """Return the registered handler or None."""
        return self._handlers.get(msg_type)

    async def dispatch(
        self,
        msg: NexusMessage,
        cipher: SessionCipher,
        websocket,
    ) -> None:
        """
        Dispatch *msg* to its registered handler.
        Logs a warning and sends an error response for unknown types.
        """
        handler = self.get(msg.type)
        if handler is None:
            log.warning("No handler registered for message type: %s", msg.type)
            await _send_error(
                cipher,
                websocket,
                f"Unknown message type: {msg.type}",
                ref_id=msg.id,
            )
            return
        try:
            await handler(msg, cipher, websocket)
        except Exception as exc:
            log.exception("Handler for '%s' raised an error: %s", msg.type, exc)
            await _send_error(cipher, websocket, str(exc), ref_id=msg.id)


registry = HandlerRegistry()

async def _send_error(
    cipher: SessionCipher,
    websocket,
    error_msg: str,
    ref_id: str = "",
) -> None:
    from nexuslink.models import NexusMessage, MsgType
    import json

    resp = NexusMessage(
        type=MsgType.ERROR,
        payload={"error": error_msg, "ref": ref_id},
    )
    if cipher:
        frame = cipher.encrypt(resp.to_bytes())
        if websocket and hasattr(websocket, "send"):
            await websocket.send(frame)
        else:
            import nexuslink.server.ws_server as ws_server
            relay = getattr(ws_server, "_firebase_relay", None)
            if relay:
                relay.send_to_phone(resp.to_bytes())
    else:
        import nexuslink.server.ws_server as ws_server
        relay = getattr(ws_server, "_firebase_relay", None)
        if relay:
            relay.send_to_phone(resp.to_bytes())
