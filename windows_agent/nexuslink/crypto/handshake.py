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
    def __init__(self) -> None:
        self._private_key: PrivateKey = PrivateKey.generate()


    @property
    def public_key_b64(self) -> str:
        raw = bytes(self._private_key.public_key)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def derive_session_key(self, peer_public_key_b64: str) -> bytes:
        peer_pub_raw = _b64url_decode(peer_public_key_b64)
        my_priv_raw = bytes(self._private_key)

        dh_output = crypto_scalarmult(my_priv_raw, peer_pub_raw)

        return _hkdf_sha256(
            ikm=dh_output,
            salt=HKDF_SALT,
            info=HKDF_INFO,
            length=SESSION_KEY_LEN,
        )

    def sign_transcript(
        self,
        signing_key,          
        my_pub_raw: bytes,
        peer_pub_raw: bytes,
    ) -> bytes:
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
        from nacl.signing import VerifyKey
        try:
            vk = VerifyKey(_b64url_decode(peer_ed25519_pub_b64))
            peer_x25519_raw = _b64url_decode(peer_x25519_pub_b64)
            transcript = peer_x25519_raw + my_x25519_pub_raw
            vk.verify(transcript, signature)
            return True
        except Exception:
            return False



def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:

    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
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
