package com.nexuslink.app.network

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Log
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.TrustedPeer
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ConnectionManager"

data class ConnectionUiState(
    val connectionState: ConnectionState = ConnectionState.Disconnected,
    val host: String = "",
    val port: Int = 0,
    val pingCount: Int = 0,
    val pongCount: Int = 0,
    val lastPongPayload: String = "",
    val lastClipboardSync: String = "",
    val errorMessage: String? = null,
)

@Singleton
class ConnectionManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val identity: IdentityManager,
    private val peerStore: PeerStore,
) {
    private val scope = CoroutineScope(Dispatchers.IO)

    private val _uiState = MutableStateFlow(ConnectionUiState())
    val uiState: StateFlow<ConnectionUiState> = _uiState

    private val _toastEvents = MutableSharedFlow<String>()
    val toastEvents: SharedFlow<String> = _toastEvents

    // Special flow to trigger notifications from the service
    private val _clipboardUpdates = MutableSharedFlow<String>()
    val clipboardUpdates: SharedFlow<String> = _clipboardUpdates

    private val _fileEvents = MutableSharedFlow<SessionEvent.MessageReceived>()
    val fileEvents: SharedFlow<SessionEvent.MessageReceived> = _fileEvents

    private val _nlpResponses = MutableSharedFlow<String>()
    val nlpResponses: SharedFlow<String> = _nlpResponses

    private val _deckShortcuts = MutableStateFlow<List<org.json.JSONObject>>(emptyList())
    val deckShortcuts: StateFlow<List<org.json.JSONObject>> = _deckShortcuts

    private var client: NexusWebSocketClient? = null
    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private var lastClipboardSent = ""

    fun connect(host: String, port: Int, peerFingerprint: String) {
        if (client != null && _uiState.value.connectionState !is ConnectionState.Disconnected) {
            disconnect()
        }

        _uiState.update { it.copy(
            host = host, 
            port = port,
            pingCount = 0,
            pongCount = 0,
            lastPongPayload = "",
            errorMessage = null,
            connectionState = ConnectionState.Connecting
        ) }

        val newClient = NexusWebSocketClient(
            host = host,
            port = port,
            identity = identity,
            peerFingerprint = peerFingerprint,
            scope = scope,
        )
        client = newClient

        scope.launch {
            newClient.state.collect { state ->
                _uiState.update { it.copy(connectionState = state) }
                if (state is ConnectionState.Error) {
                    _uiState.update { it.copy(errorMessage = state.message) }
                }
            }
        }

        scope.launch {
            for (event in newClient.events) {
                when (event) {
                    is SessionEvent.SessionEstablished -> {
                        Log.i(TAG, "Session established!")
                        _toastEvents.emit("Secure channel established!")
                        if (!peerStore.isTrusted(peerFingerprint)) {
                            peerStore.addPeer(TrustedPeer(
                                fingerprint = peerFingerprint,
                                ed25519PublicKeyB64 = event.peerEd25519PubB64,
                                displayName = host,
                            ))
                        }
                    }
                    is SessionEvent.MessageReceived -> {
                        if (event.type == "pong") {
                            _uiState.update { it.copy(
                                pongCount = it.pongCount + 1,
                                lastPongPayload = event.payload.toString(),
                            )}
                        } else if (event.type == "nlp_response") {
                            val result = event.payload.optString("result", "No result")
                            _nlpResponses.emit(result)
                        } else if (event.type == "sync_shortcuts") {
                            val arr = event.payload.optJSONArray("shortcuts")
                            val shortcuts = mutableListOf<org.json.JSONObject>()
                            if (arr != null) {
                                for (i in 0 until arr.length()) {
                                    shortcuts.add(arr.getJSONObject(i))
                                }
                            }
                            _deckShortcuts.value = shortcuts
                        } else {
                            _fileEvents.emit(event)
                        }
                    }
                    is SessionEvent.ClipboardUpdate -> {
                        val text = event.text
                        if (text.isNotBlank() && text != lastClipboardSent) {
                            lastClipboardSent = text
                            _uiState.update { it.copy(lastClipboardSync = text) }
                            _clipboardUpdates.emit(text)
                        }
                    }
                    is SessionEvent.HandshakeFailed -> {
                        _uiState.update { it.copy(errorMessage = "Handshake failed: ${event.reason}") }
                        _toastEvents.emit("Handshake failed: ${event.reason}")
                    }
                    is SessionEvent.Disconnected -> {
                        _toastEvents.emit("Disconnected from peer.")
                    }
                }
            }
        }

        newClient.connect()
    }

    fun sendPing() {
        val payload = JSONObject().apply {
            put("msg", "secure_hello")
            put("ts", System.currentTimeMillis())
        }
        client?.send("ping", payload)
        _uiState.update { it.copy(pingCount = it.pingCount + 1) }
    }

    fun pushClipboardToPc() {
        val clip = clipboardManager.primaryClip
        if (clip != null && clip.itemCount > 0) {
            val text = clip.getItemAt(0).text?.toString()
            if (!text.isNullOrBlank()) {
                sendClipboardUpdate(text)
                scope.launch { _toastEvents.emit("Clipboard pushed to PC") }
            } else {
                scope.launch { _toastEvents.emit("Android clipboard is empty") }
            }
        } else {
            scope.launch { _toastEvents.emit("Android clipboard is empty") }
        }
    }

    fun sendClipboardUpdate(text: String) {
        val payload = JSONObject().apply { put("text", text) }
        client?.send("CLIPBOARD_UPDATE", payload)
        lastClipboardSent = text
        _uiState.update { it.copy(lastClipboardSync = text) }
    }

    fun writeToAndroidClipboard(text: String) {
        val clip = ClipData.newPlainText("DeviceLink", text)
        clipboardManager.setPrimaryClip(clip)
        lastClipboardSent = text
        _uiState.update { it.copy(lastClipboardSync = text) }
    }

    suspend fun emitToast(message: String) {
        _toastEvents.emit(message)
    }

    fun sendMessage(type: String, payload: JSONObject) {
        client?.send(type, payload)
    }

    fun disconnect() {
        client?.disconnect()
        client = null
    }
}
