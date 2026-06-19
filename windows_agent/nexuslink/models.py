from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

class MsgType:
    HELLO          = "HELLO"
    HELLO_ACK      = "HELLO_ACK"
    HELLO_CONFIRM  = "HELLO_CONFIRM"
    PING           = "ping"
    PONG           = "pong"
    ERROR          = "error"

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


@dataclass
class HelloMessage:
    x25519_public_key: str    
    ed25519_public_key: str   

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
    x25519_public_key: str
    ed25519_public_key: str
    signature: str            

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
    signature: str       

    def to_nexus_message(self) -> NexusMessage:
        return NexusMessage(
            type=MsgType.HELLO_CONFIRM,
            payload={"signature": self.signature},
        )
