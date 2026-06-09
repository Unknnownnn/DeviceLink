"""
NexusLink Device Identity — Ed25519 key generation & persistence.

The agent has a single long-lived Ed25519 signing key that acts as its
permanent device identity.  The public key fingerprint is encoded in the
pairing QR code and verified by the peer before the session starts.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import RawEncoder

from config import IDENTITY_KEY_PATH


class IdentityManager:
    """Manages the persistent Ed25519 device identity."""

    def __init__(self) -> None:
        self._signing_key: SigningKey = self._load_or_generate()

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def signing_key(self) -> SigningKey:
        return self._signing_key

    @property
    def verify_key(self) -> VerifyKey:
        return self._signing_key.verify_key

    @property
    def public_key_b64(self) -> str:
        """Base64url-encoded Ed25519 public key (no padding)."""
        raw = bytes(self._signing_key.verify_key)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @property
    def fingerprint(self) -> str:
        """
        SHA-256 of the raw public key bytes, lower-hex encoded.
        This is what gets embedded in the QR code.
        """
        raw = bytes(self._signing_key.verify_key)
        return hashlib.sha256(raw).hexdigest()

    def sign(self, message: bytes) -> bytes:
        """Return the raw 64-byte Ed25519 signature over *message*."""
        signed = self._signing_key.sign(message, encoder=RawEncoder)
        return signed.signature

    @staticmethod
    def verify(verify_key_b64: str, message: bytes, signature: bytes) -> bool:
        """
        Verify *signature* over *message* using the peer's public key.
        Returns True on success, False on failure.
        """
        try:
            raw = _b64_to_bytes(verify_key_b64)
            vk = VerifyKey(raw)
            vk.verify(message, signature)
            return True
        except Exception:
            return False

    # ── Private helpers ─────────────────────────────────────────────────────

    def _load_or_generate(self) -> SigningKey:
        path = Path(IDENTITY_KEY_PATH)
        if path.exists():
            return self._load(path)
        key = SigningKey.generate()
        self._save(path, key)
        print(f"[Identity] New Ed25519 identity generated → {path}")
        return key

    @staticmethod
    def _save(path: Path, key: SigningKey) -> None:
        raw = bytes(key)  # 32-byte seed
        encoded = base64.b64encode(raw).decode()
        data = {"version": 1, "ed25519_seed_b64": encoded}
        path.write_text(json.dumps(data, indent=2))
        print(f"[Identity] Identity saved to {path}")

    @staticmethod
    def _load(path: Path) -> SigningKey:
        data = json.loads(path.read_text())
        raw = base64.b64decode(data["ed25519_seed_b64"])
        print(f"[Identity] Loaded existing identity from {path}")
        return SigningKey(raw)


# ── Utility ──────────────────────────────────────────────────────────────────

def _b64_to_bytes(s: str) -> bytes:
    """Decode Base64url (with or without padding)."""
    # Restore padding
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)
