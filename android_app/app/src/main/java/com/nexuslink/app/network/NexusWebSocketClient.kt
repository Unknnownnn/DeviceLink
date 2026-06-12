package com.nexuslink.app.network

import android.util.Log
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.decodeB64Url
import com.nexuslink.app.data.encodeB64Url
import com.nexuslink.app.network.crypto.HandshakeManager
import com.nexuslink.app.network.crypto.SessionCipher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

private const val TAG = "NexusWSClient"

/** Models the WebSocket connection lifecycle. */
sealed class ConnectionState {
    object Disconnected : ConnectionState()
    object Connecting : ConnectionState()
    object Handshaking : ConnectionState()
    data class Connected(val host: String, val port: Int) : ConnectionState()
    data class Error(val message: String) : ConnectionState()
}

/** Events emitted from the session to upper layers. */
sealed class SessionEvent {
    data class MessageReceived(val type: String, val payload: JSONObject) : SessionEvent()
    data class ClipboardUpdate(val text: String) : SessionEvent()
    data class HandshakeFailed(val reason: String) : SessionEvent()
    data class SessionEstablished(val peerEd25519PubB64: String, val deviceName: String) : SessionEvent()
    object Disconnected : SessionEvent()
}

/**
 * OkHttp WebSocket client implementing the full NexusLink handshake + encrypted
 * message session.
 *
 * Lifecycle:
 * 1. [connect] — opens WS, sends HELLO, waits for HELLO_ACK, sends HELLO_CONFIRM
 * 2. After successful handshake → derives session key → [SessionCipher] ready
 * 3. Incoming binary frames → decrypted → dispatched via [events] channel
 * 4. [send] → encrypts with session key → sends binary frame
 * 5. [disconnect] → graceful close
 */
class NexusWebSocketClient(
    private val host: String,
    private val port: Int,
    private val identity: IdentityManager,
    private val peerFingerprint: String,   // Verified from QR scan
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO),
) {
    private val okHttp = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)  // no read timeout for persistent WS
        .build()

    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = _state

    val events = Channel<SessionEvent>(Channel.BUFFERED)

    private var webSocket: WebSocket? = null
    private var cipher: SessionCipher? = null
    private val handshake = HandshakeManager()

    // ── Lifecycle ────────────────────────────────────────────────────────────

    fun connect() {
        _state.value = ConnectionState.Connecting
        val request = Request.Builder()
            .url("ws://$host:$port/")
            .build()

        webSocket = okHttp.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i(TAG, "WS opened to $host:$port — sending HELLO")
                _state.value = ConnectionState.Handshaking
                sendHello(ws)
            }

            override fun onMessage(ws: WebSocket, bytes: ByteString) {
                handleFrame(ws, bytes.toByteArray())
            }

            override fun onMessage(ws: WebSocket, text: String) {
                // All messages should be binary; text messages may arrive during handshake
                handleTextFrame(ws, text)
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WS closing: $code $reason")
                ws.close(1000, null)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WS closed: $code $reason")
                _state.value = ConnectionState.Disconnected
                scope.launch { events.send(SessionEvent.Disconnected) }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WS failure: ${t.message}")
                _state.value = ConnectionState.Error(t.message ?: "Unknown error")
                scope.launch { events.send(SessionEvent.HandshakeFailed(t.message ?: "")) }
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "User disconnected")
    }

    /**
     * Send an encrypted message.  Must only be called after [ConnectionState.Connected].
     */
    fun send(type: String, payload: JSONObject = JSONObject()) {
        val c = cipher ?: run {
            Log.w(TAG, "send() called before session established")
            return
        }
        val msg = JSONObject().apply {
            put("type", type)
            put("id", UUID.randomUUID().toString())
            put("payload", payload)
        }
        val frame = c.encrypt(msg.toString().toByteArray(Charsets.UTF_8))
        webSocket?.send(frame.toByteString())
    }

    // ── Handshake logic ───────────────────────────────────────────────────────

    private fun sendHello(ws: WebSocket) {
        val hello = JSONObject().apply {
            put("type", "HELLO")
            put("id", UUID.randomUUID().toString())
            put("payload", JSONObject().apply {
                put("x25519_public_key", handshake.publicKeyB64)
                put("ed25519_public_key", identity.publicKeyB64)
            })
        }
        ws.send(hello.toString().toByteArray().toByteString())
        Log.d(TAG, "HELLO sent")
    }

    private fun handleTextFrame(ws: WebSocket, text: String) {
        try {
            val json = JSONObject(text)
            processHandshakeMessage(ws, json)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse text frame: ${e.message}")
        }
    }

    private fun handleFrame(ws: WebSocket, bytes: ByteArray) {
        val c = cipher
        if (c == null) {
            // Still in handshake — try parsing as plaintext JSON
            try {
                val json = JSONObject(bytes.toString(Charsets.UTF_8))
                processHandshakeMessage(ws, json)
            } catch (e: Exception) {
                Log.e(TAG, "Handshake frame parse error: ${e.message}")
            }
            return
        }
        // Encrypted session
        val json: JSONObject
        try {
            val plain = c.decrypt(bytes)
            json = JSONObject(plain.toString(Charsets.UTF_8))
        } catch (e: Exception) {
            Log.e(TAG, "Decryption/parsing failed", e)
            return
        }

        val type = json.optString("type")
        val payload = json.optJSONObject("payload") ?: JSONObject()

        if (type == "CLIPBOARD_UPDATE") {
            val text = payload.optString("text", "")
            scope.launch { events.send(SessionEvent.ClipboardUpdate(text)) }
        } else {
            Log.d(TAG, "← [$type]")
            scope.launch { events.send(SessionEvent.MessageReceived(type, payload)) }
        }
    }

    private fun processHandshakeMessage(ws: WebSocket, json: JSONObject) {
        when (val type = json.optString("type")) {
            "HELLO_ACK" -> handleHelloAck(ws, json)
            else -> Log.w(TAG, "Unexpected handshake message type: $type")
        }
    }

    private fun handleHelloAck(ws: WebSocket, json: JSONObject) {
        Log.i(TAG, "HELLO_ACK received")
        try {
            val payload = json.getJSONObject("payload")
            val pcX25519B64 = payload.getString("x25519_public_key")
            val pcEd25519B64 = payload.getString("ed25519_public_key")
            val signatureB64 = payload.getString("signature")

            val pcX25519Raw = decodeB64Url(pcX25519B64)
            val transcript = pcX25519Raw + handshake.publicKeyBytes

            val pcEd25519Raw = decodeB64Url(pcEd25519B64)
            val actualFp = java.security.MessageDigest.getInstance("SHA-256")
                .digest(pcEd25519Raw)
                .joinToString("") { "%02x".format(it) }

            if (actualFp != peerFingerprint) {
                Log.e(TAG, "HELLO_ACK fingerprint mismatch! Expected $peerFingerprint, got $actualFp")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Key fingerprint mismatch")) }
                ws.close(1008, "Fingerprint mismatch")
                return
            }

            val sigRaw = decodeB64Url(signatureB64)
            val verified = identity.verify(pcEd25519B64, transcript, sigRaw)

            if (!verified) {
                Log.e(TAG, "HELLO_ACK signature verification FAILED — aborting handshake")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Signature verification failed")) }
                ws.close(1008, "Signature verification failed")
                return
            }
            Log.i(TAG, "HELLO_ACK signature verified ✓")

            // 2. Sign (android_x25519_pub || pc_x25519_pub) and send HELLO_CONFIRM
            val myTranscript = handshake.publicKeyBytes + pcX25519Raw
            val mySignature = identity.sign(myTranscript)
            val mySignatureB64 = encodeB64Url(mySignature)

            val confirm = JSONObject().apply {
                put("type", "HELLO_CONFIRM")
                put("id", UUID.randomUUID().toString())
                put("payload", JSONObject().apply {
                    put("signature", mySignatureB64)
                })
            }
            ws.send(confirm.toString().toByteArray().toByteString())
            Log.i(TAG, "HELLO_CONFIRM sent")

            // 3. Derive session key
            val sessionKey = handshake.deriveSessionKey(pcX25519B64)
            cipher = SessionCipher(sessionKey)
            Log.i(TAG, "Session key derived ✓ — secure channel established!")

            val deviceName = payload.optString("device_name", host)
            _state.value = ConnectionState.Connected(host, port)
            scope.launch { events.send(SessionEvent.SessionEstablished(pcEd25519B64, deviceName)) }

        } catch (e: Exception) {
            Log.e(TAG, "handleHelloAck error: ${e.message}", e)
            scope.launch { events.send(SessionEvent.HandshakeFailed(e.message ?: "Unknown")) }
        }
    }
}
