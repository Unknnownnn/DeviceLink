package com.nexuslink.app.network.crypto

import android.util.Log
import com.google.crypto.tink.aead.AeadConfig
import com.google.crypto.tink.subtle.ChaCha20Poly1305
import java.security.SecureRandom
import javax.inject.Inject

private const val TAG = "SessionCipher"
private const val NONCE_LEN = 12   // 96-bit nonce for ChaCha20-Poly1305

/**
 * Stateless AEAD session cipher using ChaCha20-Poly1305 (via Google Tink).
 *
 * Frame format (binary WebSocket frame):
 *   [12 bytes random nonce][N bytes ciphertext + 16 bytes Poly1305 tag]
 *
 * Wire overhead per message: 28 bytes (12 nonce + 16 tag).
 *
 * Thread-safe: each call generates a fresh random nonce.
 */
class SessionCipher(private val sessionKey: ByteArray) {

    init {
        require(sessionKey.size == 32) {
            "ChaCha20-Poly1305 key must be 32 bytes, got ${sessionKey.size}"
        }
    }

    private val aead = ChaCha20Poly1305(sessionKey)
    private val random = SecureRandom()

    /**
     * Encrypt [plaintext] and return a binary WebSocket frame:
     *   `nonce (12 bytes) || ciphertext+tag (N+16 bytes)`
     */
    fun encrypt(plaintext: ByteArray): ByteArray {
        // Tink's ChaCha20Poly1305 automatically generates a 12-byte nonce
        // and prepends it to the output.
        return aead.encrypt(plaintext, null)
    }

    /**
     * Decrypt a binary WebSocket frame.
     *
     * @param frame The raw frame bytes (nonce prepended).
     * @return Decrypted plaintext bytes.
     * @throws GeneralSecurityException on authentication failure.
     * @throws IllegalArgumentException if the frame is too short.
     */
    fun decrypt(frame: ByteArray): ByteArray {
        require(frame.size > NONCE_LEN) {
            "Frame too short: ${frame.size} bytes"
        }
        // Tink's decrypt expects the 12-byte nonce to be prepended to the ciphertext.
        return aead.decrypt(frame, null)
    }
}
