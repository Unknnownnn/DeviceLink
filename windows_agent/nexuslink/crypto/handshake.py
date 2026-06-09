"""
NexusLink Crypto — X25519 ECDH Handshake + HKDF Key Derivation

Performs the client-authenticated key exchange:

  1. Generate an ephemeral X25519 key pair for this session.
  2. Exchange public keys with the peer.
  3. Derive a 256-bit session key via HKDF-SHA256.
  4. Optionally bind the derived key to both parties' Ed25519 identities
     by requiring a cross-signed transcript.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Tuple

from nacl.public import PrivateKey, PublicKey
from nacl.bindings import crypto_scalarmult

from config import HKDF_INFO, HKDF_SALT, SESSION_KEY_LEN


class HandshakeManager:
    """
    Manages one ephemeral X25519 key pair per session.

    Usage::

        hs = HandshakeManager()
        my_pub_b64 = hs.public_key_b64   # send to peer
        session_key = hs.derive_session_key(peer_pub_b64)
    """

    def __init__(self) -> None:
        self._private_key: PrivateKey = PrivateKey.generate()

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def public_key_b64(self) -> str:
        """Base64url-encoded X25519 ephemeral public key (no padding)."""
        raw = bytes(self._private_key.public_key)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def derive_session_key(self, peer_public_key_b64: str) -> bytes:
        """
        Perform X25519(my_priv, peer_pub) and run HKDF-SHA256 to produce a
        32-byte ChaCha20-Poly1305 session key.

        Args:
            peer_public_key_b64: The peer's X25519 ephemeral public key,
                                 Base64url-encoded (padding optional).

        Returns:
            32 bytes of derived keying material.
        """
        peer_pub_raw = _b64url_decode(peer_public_key_b64)
        my_priv_raw = bytes(self._private_key)

        # Raw DH output — 32 bytes
        dh_output = crypto_scalarmult(my_priv_raw, peer_pub_raw)

        # HKDF-SHA256: extract + expand
        return _hkdf_sha256(
            ikm=dh_output,
            salt=HKDF_SALT,
            info=HKDF_INFO,
            length=SESSION_KEY_LEN,
        )

    def sign_transcript(
        self,
        signing_key,          # nacl.signing.SigningKey
        my_pub_raw: bytes,
        peer_pub_raw: bytes,
    ) -> bytes:
        """
        Produce an Ed25519 signature over (my_x25519_pub || peer_x25519_pub)
        to authenticate this side of the handshake.
        """
        from nacl.encoding import RawEncoder
        transcript = my_pub_raw + peer_pub_raw
        return signing_key.sign(transcript, encoder=RawEncoder).signature

    def verify_transcript(
        self,
        peer_ed25519_pub_b64: str,
        peer_x25519_pub_b64: str,
        my_x25519_pub_raw: bytes,
        signature: bytes,
    ) -> bool:
        """
        Verify the peer's Ed25519 signature over (peer_x25519_pub || my_x25519_pub).
        Returns True if valid.
        """
        from nacl.signing import VerifyKey
        try:
            vk = VerifyKey(_b64url_decode(peer_ed25519_pub_b64))
            peer_x25519_raw = _b64url_decode(peer_x25519_pub_b64)
            transcript = peer_x25519_raw + my_x25519_pub_raw
            vk.verify(transcript, signature)
            return True
        except Exception:
            return False


# ── HKDF helpers ─────────────────────────────────────────────────────────────

def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """Minimal HKDF-SHA256 (RFC 5869)."""
    # Extract
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    # Expand
    output = b""
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(
            prk, previous + info + bytes([counter]), hashlib.sha256
        ).digest()
        output += previous
        counter += 1
    return output[:length]


def _b64url_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)
