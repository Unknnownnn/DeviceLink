"""
NexusLink Protocol Message Models
"""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


# ── Message Type Constants ────────────────────────────────────────────────────

class MsgType:
    # Handshake (plaintext phase)
    HELLO          = "HELLO"
    HELLO_ACK      = "HELLO_ACK"
    HELLO_CONFIRM  = "HELLO_CONFIRM"
    # Encrypted phase
    PING           = "ping"
    PONG           = "pong"
    ERROR          = "error"


# ── Base Message ──────────────────────────────────────────────────────────────

@dataclass
class NexusMessage:
    type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "NexusMessage":
        raw = json.loads(data.decode("utf-8"))
        return cls(
            type=raw["type"],
            id=raw.get("id", str(uuid.uuid4())),
            payload=raw.get("payload", {}),
        )

    @classmethod
    def from_json(cls, s: str) -> "NexusMessage":
        return cls.from_bytes(s.encode("utf-8"))


# ── Handshake Messages ────────────────────────────────────────────────────────

@dataclass
class HelloMessage:
    """Sent by Android → PC: initiates ECDH key exchange."""
    x25519_public_key: str    # Base64url-encoded X25519 ephemeral public key
    ed25519_public_key: str   # Base64url-encoded Ed25519 identity public key

    def to_nexus_message(self) -> NexusMessage:
        return NexusMessage(
            type=MsgType.HELLO,
            payload={
                "x25519_public_key": self.x25519_public_key,
                "ed25519_public_key": self.ed25519_public_key,
            },
        )


@dataclass
class HelloAckMessage:
    """Sent by PC → Android: responds with own keys + signature."""
    x25519_public_key: str
    ed25519_public_key: str
    signature: str            # Ed25519 signature over (android_x25519_pub || pc_x25519_pub)

    def to_nexus_message(self) -> NexusMessage:
        return NexusMessage(
            type=MsgType.HELLO_ACK,
            payload={
                "x25519_public_key": self.x25519_public_key,
                "ed25519_public_key": self.ed25519_public_key,
                "signature": self.signature,
            },
        )


@dataclass
class HelloConfirmMessage:
    """Sent by Android → PC: confirms the handshake with its own signature."""
    signature: str            # Ed25519 signature over (pc_x25519_pub || android_x25519_pub)

    def to_nexus_message(self) -> NexusMessage:
        return NexusMessage(
            type=MsgType.HELLO_CONFIRM,
            payload={"signature": self.signature},
        )
