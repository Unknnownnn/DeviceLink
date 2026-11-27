package com.nexuslink.app.data

import android.content.Context
import android.util.AtomicFile
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "PeerStore"
private const val PEERS_FILE = "trusted_peers.json"

/**
 * Persists trusted peer (PC) entries on disk as a JSON object keyed by fingerprint.
 *
 * A "peer" is a PC whose Ed25519 fingerprint was pinned by a QR scan.
 * Once paired, the device can reconnect without re-scanning the QR code.
 */
@Singleton
class PeerStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val file = AtomicFile(File(context.filesDir, PEERS_FILE))

    private val _peers = MutableStateFlow<Map<String, TrustedPeer>>(emptyMap())
    val peers: StateFlow<Map<String, TrustedPeer>> = _peers

    init {
        _peers.value = loadFromDisk()
    }

    // ── Public API ──────────────────────────────────────────────────────────

    @Synchronized
    fun rememberPairing(fingerprint: String, endpoint: LanEndpoint) {
        val peer = getPeer(fingerprint) ?: TrustedPeer(fingerprint, displayName = endpoint.host)
        savePeer(peer.copy(lanEndpoint = endpoint))
    }

    @Synchronized
    fun confirmPeer(
        fingerprint: String,
        publicKeyB64: String,
        displayName: String? = null,
        lanEndpoint: LanEndpoint? = null,
    ) {
        val peer = getPeer(fingerprint) ?: return
        try {
            savePeer(peer.copy(
                ed25519PublicKeyB64 = publicKeyB64,
                displayName = displayName?.takeIf { it.isNotBlank() } ?: peer.displayName,
                lanEndpoint = lanEndpoint ?: peer.lanEndpoint,
            ))
        } catch (e: IOException) {
            Log.w(TAG, "Failed to update saved peer: ${peer.displayName}", e)
        }
    }

    private fun savePeer(peer: TrustedPeer) {
        if (getPeer(peer.fingerprint) == peer) return
        savePeers(_peers.value + (peer.fingerprint to peer))
        Log.i(TAG, "Trusted peer saved: ${peer.displayName} [${peer.fingerprint.take(12)}…]")
    }

    @Synchronized
    fun removePeer(fingerprint: String) {
        savePeers(_peers.value - fingerprint)
        Log.i(TAG, "Trusted peer removed: $fingerprint")
    }

    fun getPeer(fingerprint: String): TrustedPeer? = _peers.value[fingerprint]

    // ── Persistence ─────────────────────────────────────────────────────────

    private fun loadFromDisk(): Map<String, TrustedPeer> {
        return try {
            val json = JSONObject(file.readFully().toString(Charsets.UTF_8))
            buildMap {
                json.keys().forEach { key ->
                    val obj = json.optJSONObject(key) ?: return@forEach
                    val host = obj.optString("host")
                    val port = obj.optInt("port")
                    put(key, TrustedPeer(
                        fingerprint = key,
                        ed25519PublicKeyB64 = obj.optString("ed25519_pub").ifBlank { null },
                        displayName = obj.optString("name", key.take(8)),
                        lanEndpoint = if (host.isNotBlank() && port in 1..65535) LanEndpoint(host, port) else null,
                    ))
                }
            }
        } catch (e: FileNotFoundException) {
            emptyMap()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to load peers: ${e.message}")
            emptyMap()
        }
    }

    private fun savePeers(peers: Map<String, TrustedPeer>) {
        val json = JSONObject()
        peers.forEach { (fp, peer) ->
            json.put(fp, JSONObject().apply {
                put("ed25519_pub", peer.ed25519PublicKeyB64)
                put("name", peer.displayName)
                peer.lanEndpoint?.let { endpoint ->
                    put("host", endpoint.host)
                    put("port", endpoint.port)
                }
            })
        }
        val output = file.startWrite()
        try {
            output.write(json.toString(2).toByteArray(Charsets.UTF_8))
            file.finishWrite(output)
        } catch (e: Exception) {
            file.failWrite(output)
            throw e
        }
        _peers.value = peers
    }
}

/**
 * A paired PC. Only a successful direct handshake supplies the full public key.
 */
data class TrustedPeer(
    val fingerprint: String,
    val ed25519PublicKeyB64: String? = null,
    val displayName: String,
    val lanEndpoint: LanEndpoint? = null,
)

data class LanEndpoint(val host: String, val port: Int)
