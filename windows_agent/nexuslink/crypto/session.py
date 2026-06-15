from __future__ import annotations

import os
from nacl.bindings import (
    crypto_aead_chacha20poly1305_ietf_encrypt,
    crypto_aead_chacha20poly1305_ietf_decrypt,
    crypto_aead_chacha20poly1305_ietf_NPUBBYTES,   
    crypto_aead_chacha20poly1305_ietf_KEYBYTES,    
)

NONCE_BYTES = crypto_aead_chacha20poly1305_ietf_NPUBBYTES  
KEY_BYTES = crypto_aead_chacha20poly1305_ietf_KEYBYTES    


class SessionCipher:
    def __init__(self, session_key: bytes) -> None:
        if len(session_key) != KEY_BYTES:
            raise ValueError(
                f"Session key must be {KEY_BYTES} bytes, got {len(session_key)}"
            )
        self._key = session_key


    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = crypto_aead_chacha20poly1305_ietf_encrypt(
            message=plaintext,
            aad=None,
            nonce=nonce,
            key=self._key,
        )
        return nonce + ciphertext

    def decrypt(self, frame: bytes) -> bytes:
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
