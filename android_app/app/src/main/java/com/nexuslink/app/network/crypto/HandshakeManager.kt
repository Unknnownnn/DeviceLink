package com.nexuslink.app.network.crypto

import android.util.Log
import com.nexuslink.app.data.decodeB64Url
import com.nexuslink.app.data.encodeB64Url
import com.google.crypto.tink.subtle.X25519
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.inject.Inject

private const val TAG = "HandshakeManager"
private const val HKDF_INFO = "devicelink-session-v1"
private const val HKDF_SALT = "devicelink-hkdf-salt-v1"
private const val SESSION_KEY_LEN = 32

/**
 * Manages an ephemeral X25519 key pair for a single session.
 *
 * Usage:
 * 1. Obtain [publicKeyB64] and send to PC in HELLO message.
 * 2. Call [deriveSessionKey] with the PC's X25519 public key (from HELLO_ACK).
 * 3. Use the returned [ByteArray] as the ChaCha20-Poly1305 session key.
 *
 * A new [HandshakeManager] instance MUST be created per connection session.
 */
class HandshakeManager @Inject constructor() {

    // Ephemeral X25519 private key (32 bytes)
    private val privateKey: ByteArray = X25519.generatePrivateKey()

    // Derived public key (32 bytes)
    private val publicKey: ByteArray = X25519.publicFromPrivate(privateKey)

    /** Base64url-encoded X25519 ephemeral public key (no padding). */
    val publicKeyB64: String = encodeB64Url(publicKey)

    /** Raw public key bytes (32 bytes). */
    val publicKeyBytes: ByteArray = publicKey

    /**
     * Perform X25519 DH with the peer's public key and derive a 32-byte
     * session key via HKDF-SHA256.
     *
     * @param peerPublicKeyB64 The peer's X25519 ephemeral public key, Base64url-encoded.
     * @return 32-byte session key for ChaCha20-Poly1305.
     */
    fun deriveSessionKey(peerPublicKeyB64: String): ByteArray {
        val peerPubRaw = decodeB64Url(peerPublicKeyB64)
        val dhOutput = X25519.computeSharedSecret(privateKey, peerPubRaw)
        return hkdfSha256(
            ikm = dhOutput,
            salt = HKDF_SALT.toByteArray(Charsets.UTF_8),
            info = HKDF_INFO.toByteArray(Charsets.UTF_8),
            length = SESSION_KEY_LEN,
        )
    }

    /**
     * Produce the signing transcript for our side of the handshake.
     *
     * PC signs:   (pc_x25519_pub  || android_x25519_pub)
     * Android signs: (android_x25519_pub || pc_x25519_pub)
     *
     * @param peerPublicKeyBytes The peer's raw X25519 public key bytes.
     * @return The transcript bytes to sign.
     */
    fun buildSigningTranscript(peerPublicKeyBytes: ByteArray): ByteArray =
        publicKey + peerPublicKeyBytes

    // ── HKDF helpers ─────────────────────────────────────────────────────────

    private fun hkdfSha256(
        ikm: ByteArray,
        salt: ByteArray,
        info: ByteArray,
        length: Int,
    ): ByteArray {
        // Extract
        val prk = hmacSha256(salt, ikm)
        // Expand
        val result = mutableListOf<Byte>()
        var previous = ByteArray(0)
        var counter = 1
        while (result.size < length) {
            previous = hmacSha256(prk, previous + info + byteArrayOf(counter.toByte()))
            result.addAll(previous.toList())
            counter++
        }
        return result.take(length).toByteArray()
    }

    private fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }
}
