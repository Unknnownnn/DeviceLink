package com.nexuslink.app.data

import android.content.Context
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "PeerStore"
private const val PEERS_FILE = "trusted_peers.json"

/**
 * Persists trusted peer (PC) entries on disk as a JSON object keyed by fingerprint.
 *
 * A "peer" is a PC whose Ed25519 fingerprint was verified during QR pairing.
 * Once paired, the device can reconnect without re-scanning the QR code.
 */
@Singleton
class PeerStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val file: File by lazy { File(context.filesDir, PEERS_FILE) }

    private val _peers = MutableStateFlow<Map<String, TrustedPeer>>(emptyMap())
    val peers: StateFlow<Map<String, TrustedPeer>> = _peers

    init {
        _peers.value = loadFromDisk()
    }

    // ── Public API ──────────────────────────────────────────────────────────

    fun addPeer(peer: TrustedPeer) {
        val updated = _peers.value.toMutableMap().apply { put(peer.fingerprint, peer) }
        _peers.value = updated
        saveToDisk(updated)
        Log.i(TAG, "Trusted peer saved: ${peer.displayName} [${peer.fingerprint.take(12)}…]")
    }

    fun removePeer(fingerprint: String) {
        val updated = _peers.value.toMutableMap().apply { remove(fingerprint) }
        _peers.value = updated
        saveToDisk(updated)
        Log.i(TAG, "Trusted peer removed: $fingerprint")
    }

    fun isTrusted(fingerprint: String): Boolean = _peers.value.containsKey(fingerprint)

    fun getPeer(fingerprint: String): TrustedPeer? = _peers.value[fingerprint]

    // ── Persistence ─────────────────────────────────────────────────────────

    private fun loadFromDisk(): Map<String, TrustedPeer> {
        if (!file.exists()) return emptyMap()
        return try {
            val json = JSONObject(file.readText())
            buildMap {
                json.keys().forEach { key ->
                    val obj = json.getJSONObject(key)
                    put(key, TrustedPeer(
                        fingerprint = key,
                        ed25519PublicKeyB64 = obj.getString("ed25519_pub"),
                        displayName = obj.optString("name", key.take(8)),
                    ))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to load peers: ${e.message}")
            emptyMap()
        }
    }

    private fun saveToDisk(peers: Map<String, TrustedPeer>) {
        val json = JSONObject()
        peers.forEach { (fp, peer) ->
            json.put(fp, JSONObject().apply {
                put("ed25519_pub", peer.ed25519PublicKeyB64)
                put("name", peer.displayName)
            })
        }
        file.writeText(json.toString(2))
    }
}

/**
 * A verified, trusted PC peer.
 */
data class TrustedPeer(
    val fingerprint: String,
    val ed25519PublicKeyB64: String,
    val displayName: String,
)
