"""
NexusLink Crypto — ChaCha20-Poly1305 Session Cipher

Provides stateless encrypt/decrypt helpers using PyNaCl's SecretBox
(XSalsa20-Poly1305) … wait — the spec calls for ChaCha20-Poly1305
(RFC 8439).  PyNaCl wraps libsodium which exposes
`crypto_aead_chacha20poly1305_ietf_*` — we use those bindings directly.

Frame format (binary):
    [12 bytes random nonce][N bytes ciphertext+tag]

Total overhead per message: 12 (nonce) + 16 (Poly1305 tag) = 28 bytes.
"""
from __future__ import annotations

import os
from nacl.bindings import (
    crypto_aead_chacha20poly1305_ietf_encrypt,
    crypto_aead_chacha20poly1305_ietf_decrypt,
    crypto_aead_chacha20poly1305_ietf_NPUBBYTES,   # 12
    crypto_aead_chacha20poly1305_ietf_KEYBYTES,    # 32
)

NONCE_BYTES = crypto_aead_chacha20poly1305_ietf_NPUBBYTES  # 12
KEY_BYTES = crypto_aead_chacha20poly1305_ietf_KEYBYTES     # 32


class SessionCipher:
    """
    Stateless AEAD cipher for a single established session.

    The same key is used for both directions; the random nonce ensures
    ciphertext uniqueness even when the same plaintext is sent twice.
    """

    def __init__(self, session_key: bytes) -> None:
        if len(session_key) != KEY_BYTES:
            raise ValueError(
                f"Session key must be {KEY_BYTES} bytes, got {len(session_key)}"
            )
        self._key = session_key

    # ── Public API ──────────────────────────────────────────────────────────

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt *plaintext* and return ``nonce || ciphertext`` (binary frame).

        Args:
            plaintext: Raw bytes to encrypt (typically a JSON-encoded payload).

        Returns:
            Binary WebSocket frame ready for transmission.
        """
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = crypto_aead_chacha20poly1305_ietf_encrypt(
            message=plaintext,
            aad=None,
            nonce=nonce,
            key=self._key,
        )
        return nonce + ciphertext

    def decrypt(self, frame: bytes) -> bytes:
        """
        Decrypt a ``nonce || ciphertext`` frame received from the peer.

        Args:
            frame: Binary WebSocket frame (nonce prepended).

        Returns:
            Decrypted plaintext bytes.

        Raises:
            nacl.exceptions.CryptoError: On authentication failure.
            ValueError: If the frame is too short to contain a nonce.
        """
        if len(frame) < NONCE_BYTES:
            raise ValueError(
                f"Frame too short: {len(frame)} < {NONCE_BYTES} bytes"
            )
        nonce, ciphertext = frame[:NONCE_BYTES], frame[NONCE_BYTES:]
        return crypto_aead_chacha20poly1305_ietf_decrypt(
            ciphertext=ciphertext,
            aad=None,
            nonce=nonce,
            key=self._key,
        )
