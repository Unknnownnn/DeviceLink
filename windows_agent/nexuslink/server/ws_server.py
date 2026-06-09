from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from config import WS_HOST, WS_PORT
from nexuslink.crypto import HandshakeManager, SessionCipher
from nexuslink.identity import IdentityManager
from nexuslink.models import NexusMessage, MsgType
from nexuslink.server.handlers import registry
from nexuslink.server import ping_handler
from nexuslink.server import clipboard_handler
from nexuslink.server import file_handler
from nexuslink.server import dropzone_watcher
from nexuslink.server import agent_orchestrator
from nexuslink.server import power_handler

log = logging.getLogger("nexuslink.ws_server")

ping_handler.register(registry)
clipboard_handler.register(registry)
file_handler.register(registry)
agent_orchestrator.register(registry)
power_handler.register(registry)


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

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            # Binary subprotocol — all frames are bytes
            max_size=10 * 1024 * 1024,  # 10 MB max frame size
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

    # ── Connection handler ──────────────────────────────────────────────────

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

            # Send dynamic deck shortcuts
            from nexuslink.settings_manager import SettingsManager
            settings = SettingsManager()
            shortcuts_msg = NexusMessage(
                type="sync_shortcuts",
                payload={"shortcuts": settings.get_deck_shortcuts()}
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
            log.info("Peer disconnected: %s", peer)
            print(f"[Server] ✗ Peer disconnected: {peer}")

    # ── Handshake ───────────────────────────────────────────────────────────

    async def _do_handshake(
        self,
        ws: WebSocketServerProtocol,
    ) -> Optional[SessionCipher]:
        """
        Execute the 3-message X25519 + Ed25519 handshake.
        Returns a SessionCipher on success, None on failure.
        """
        # ── Step 1: Receive HELLO ──
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

        # ── Step 2: Generate our ephemeral X25519 key + sign transcript ──
        hs = HandshakeManager()
        my_x25519_pub_raw = _b64url_decode(hs.public_key_b64)
        client_x25519_raw = _b64url_decode(client_x25519_b64)

        # Sign (my_x25519_pub || client_x25519_pub) with our Ed25519 identity key
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

        # ── Step 3: Receive HELLO_CONFIRM ──
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

        # Verify client signature over (client_x25519_pub || my_x25519_pub)
        client_sig_raw = _b64url_decode(confirm.payload["signature"])
        transcript_expected = client_x25519_raw + my_x25519_pub_raw
        client_ed25519_raw = _b64url_decode(client_ed25519_b64)

        if not _verify_ed25519(client_ed25519_raw, transcript_expected, client_sig_raw):
            log.warning("HELLO_CONFIRM signature verification FAILED")
            return None

        log.info("HELLO_CONFIRM signature verified ✓")

        # ── Step 4: Derive session key ──
        session_key = hs.derive_session_key(client_x25519_b64)
        log.info("Session key derived (32 bytes) ✓")
        return SessionCipher(session_key)

    # ── Session loop ─────────────────────────────────────────────────────────

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


# ── Crypto helpers ────────────────────────────────────────────────────────────

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
