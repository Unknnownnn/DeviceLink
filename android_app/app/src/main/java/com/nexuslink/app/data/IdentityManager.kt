package com.nexuslink.app.data

import android.content.Context
import android.util.Log
import com.google.crypto.tink.KeysetHandle
import com.google.crypto.tink.signature.Ed25519PrivateKeyManager
import com.google.crypto.tink.signature.SignatureConfig
import com.google.crypto.tink.subtle.Ed25519Sign
import com.google.crypto.tink.subtle.Ed25519Verify
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.security.MessageDigest
import java.util.Base64
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "IdentityManager"
private const val KEY_FILE = "nexuslink_identity.json"

/**
 * Manages the device's persistent Ed25519 identity key using Google Tink.
 *
 * The key is generated once and stored in the app's private files directory.
 * The public key fingerprint (SHA-256 hex) is used for device identification
 * and is verified during pairing.
 */
@Singleton
class IdentityManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    private val keyFile: File by lazy { File(context.filesDir, KEY_FILE) }

    // Raw 32-byte Ed25519 private key seed (generated or loaded from disk).
    // In production, this should be stored in Android Keystore. For Phase 1,
    // we store it in the app private files directory.
    private val _privateKeyBytes: ByteArray by lazy { loadOrGenerateKey() }

    // ── Public API ──────────────────────────────────────────────────────────

    /** Raw 32-byte Ed25519 public key. */
    val publicKeyBytes: ByteArray by lazy {
        Ed25519Sign.KeyPair.newKeyPairFromSeed(_privateKeyBytes).publicKey
    }

    /** Base64url-encoded Ed25519 public key (no padding). */
    val publicKeyB64: String by lazy {
        Base64.getUrlEncoder().withoutPadding().encodeToString(publicKeyBytes)
    }

    /** SHA-256 hex fingerprint of the Ed25519 public key. */
    val fingerprint: String by lazy {
        MessageDigest.getInstance("SHA-256")
            .digest(publicKeyBytes)
            .joinToString("") { "%02x".format(it) }
    }

    /**
     * Sign [message] with the device's Ed25519 private key.
     * @return 64-byte raw Ed25519 signature.
     */
    fun sign(message: ByteArray): ByteArray {
        val signer = Ed25519Sign(_privateKeyBytes)
        return signer.sign(message)
    }

    /**
     * Verify a signature from a remote peer.
     * @param publicKeyB64 Base64url-encoded Ed25519 public key of the peer.
     * @param message      The message that was signed.
     * @param signature    The 64-byte signature to verify.
     * @return true if the signature is valid.
     */
    fun verify(publicKeyB64: String, message: ByteArray, signature: ByteArray): Boolean {
        return try {
            val pubKey = decodeB64Url(publicKeyB64)
            Ed25519Verify(pubKey).verify(signature, message)
            true
        } catch (e: Exception) {
            Log.w(TAG, "Signature verification failed: ${e.message}")
            false
        }
    }

    // ── Private helpers ─────────────────────────────────────────────────────

    private fun loadOrGenerateKey(): ByteArray {
        if (keyFile.exists()) {
            return try {
                val encoded = keyFile.readText().trim()
                decodeB64Url(encoded).also {
                    Log.i(TAG, "Loaded existing Ed25519 identity key.")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed to load key, regenerating: ${e.message}")
                generateAndSave()
            }
        }
        return generateAndSave()
    }

    private fun generateAndSave(): ByteArray {
        val keyPair = Ed25519Sign.KeyPair.newKeyPair()
        // Store only the 32-byte seed (private key)
        val seed = keyPair.privateKey.copyOfRange(0, 32)
        val encoded = Base64.getUrlEncoder().withoutPadding().encodeToString(seed)
        keyFile.writeText(encoded)
        Log.i(TAG, "Generated new Ed25519 identity key.")
        return seed
    }
}

// ── Utility ───────────────────────────────────────────────────────────────────

internal fun decodeB64Url(s: String): ByteArray {
    val normalized = s.replace('-', '+').replace('_', '/')
    val padded = normalized + "=".repeat((4 - normalized.length % 4) % 4)
    return Base64.getDecoder().decode(padded)
}

internal fun encodeB64Url(bytes: ByteArray): String =
    Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
