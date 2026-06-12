package com.nexuslink.app.network

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Log
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.TrustedPeer
import com.nexuslink.app.services.CallBridgeManager
import com.nexuslink.app.services.ConnManagerProxy
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
    val lastClipboardSync: String = "",
    val errorMessage: String? = null,
    val logs: List<String> = emptyList(),
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

    // ── Call bridge events (incoming call data from phone) ──────────────────
    data class IncomingCallInfo(val number: String, val name: String)
    private val _incomingCallEvents = MutableSharedFlow<IncomingCallInfo>()
    val incomingCallEvents: SharedFlow<IncomingCallInfo> = _incomingCallEvents

    // ── Bluetooth HFP state ─────────────────────────────────────────────────
    val bluetoothConnected: StateFlow<Boolean> = CallBridgeManager.bluetoothConnected

    private var client: NexusWebSocketClient? = null
    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private var lastClipboardSent = ""

    init {
        // Register this manager so non-Hilt singletons can send WebSocket messages
        ConnManagerProxy.register(this)
        // Initial Bluetooth state check
        CallBridgeManager.refreshBluetoothState(context)
    }

    fun addLog(message: String) {
        val hasTimestamp = message.length >= 8 && message.substring(0, 8).matches(Regex("\\d{2}:\\d{2}:\\d{2}"))
        val logLine = if (hasTimestamp) {
            message
        } else {
            val timestamp = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
            "[$timestamp] $message"
        }
        _uiState.update { state ->
            val updatedLogs = state.logs + logLine
            state.copy(logs = if (updatedLogs.size > 100) updatedLogs.takeLast(100) else updatedLogs)
        }
    }

    fun connect(host: String, port: Int, peerFingerprint: String) {
        if (client != null && _uiState.value.connectionState !is ConnectionState.Disconnected) {
            disconnect()
        }

        _uiState.update { it.copy(
            host = host, 
            port = port,
            errorMessage = null,
            connectionState = ConnectionState.Connecting,
            logs = emptyList() // Clear logs on new connection
        ) }

        addLog("Connecting to secure server $host:$port...")

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
                when (state) {
                    is ConnectionState.Connecting -> addLog("Connection status: Connecting...")
                    is ConnectionState.Handshaking -> addLog("Connection status: Handshaking...")
                    is ConnectionState.Error -> {
                        _uiState.update { it.copy(errorMessage = state.message) }
                        addLog("Connection error: ${state.message}")
                    }
                    else -> {}
                }
            }
        }

        scope.launch {
            for (event in newClient.events) {
                when (event) {
                    is SessionEvent.SessionEstablished -> {
                        Log.i(TAG, "Session established!")
                        _toastEvents.emit("Secure channel established!")
                        addLog("Secure session established with peer: ${event.deviceName}")
                        val existingPeer = peerStore.getPeer(peerFingerprint)
                        if (existingPeer == null || existingPeer.displayName != event.deviceName) {
                            peerStore.addPeer(TrustedPeer(
                                fingerprint = peerFingerprint,
                                ed25519PublicKeyB64 = event.peerEd25519PubB64,
                                displayName = event.deviceName,
                            ))
                        }
                    }
                    is SessionEvent.MessageReceived -> {
                        if (event.type == "nlp_response") {
                            val result = event.payload.optString("result", "No result")
                            addLog("AI Command Result: $result")
                            _nlpResponses.emit(result)
                        } else if (event.type == "sync_shortcuts") {
                            val arr = event.payload.optJSONArray("shortcuts")
                            val shortcuts = mutableListOf<org.json.JSONObject>()
                            if (arr != null) {
                                for (i in 0 until arr.length()) {
                                    shortcuts.add(arr.getJSONObject(i))
                                }
                            }
                            addLog("Synced ${shortcuts.size} deck shortcuts from PC")
                            _deckShortcuts.value = shortcuts
                        } else if (event.type == "make_call") {
                            val number = event.payload.optString("number", "")
                            if (number.isNotBlank()) {
                                addLog("Incoming phone call request dialer: $number")
                                CallBridgeManager.onMakeCall(context, number)
                            }
                        } else if (event.type == "request_contacts") {
                            addLog("Contacts list sync request from PC")
                            CallBridgeManager.syncContactsToPC(context)
                        } else if (event.type == "call_action") {
                            val action = event.payload.optString("action", "")
                            Log.d(TAG, "call_action from PC: $action")
                            addLog("Call bridge action executed: $action")
                            when (action) {
                                "answer" -> CallBridgeManager.answerCall(context)
                                "decline" -> CallBridgeManager.declineCall(context)
                                "hangup" -> CallBridgeManager.hangUpCall(context)
                            }
                        } else if (event.type == "pc_log") {
                            val pcLog = event.payload.optString("log", "")
                            if (pcLog.isNotBlank()) {
                                pcLog.split("\n").forEach { line ->
                                    if (line.trim().isNotBlank()) {
                                        addLog(line.trim())
                                    }
                                }
                            }
                        } else {
                            addLog("Received peer message: ${event.type}")
                            _fileEvents.emit(event)
                        }
                    }
                    is SessionEvent.ClipboardUpdate -> {
                        val text = event.text
                        if (text.isNotBlank() && text != lastClipboardSent) {
                            lastClipboardSent = text
                            _uiState.update { it.copy(lastClipboardSync = text) }
                            addLog("Received clipboard sync from PC")
                            _clipboardUpdates.emit(text)
                        }
                    }
                    is SessionEvent.HandshakeFailed -> {
                        _uiState.update { it.copy(errorMessage = "Handshake failed: ${event.reason}") }
                        _toastEvents.emit("Handshake failed: ${event.reason}")
                        addLog("Handshake failed: ${event.reason}")
                    }
                    is SessionEvent.Disconnected -> {
                        _toastEvents.emit("Disconnected from peer.")
                        addLog("Disconnected from peer.")
                    }
                }
            }
        }

        newClient.connect()
    }

    fun pushClipboardToPc() {
        val clip = clipboardManager.primaryClip
        if (clip != null && clip.itemCount > 0) {
            val text = clip.getItemAt(0).text?.toString()
            if (!text.isNullOrBlank()) {
                addLog("Clipboard text synced to PC")
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
        when (type) {
            "nlp_command" -> addLog("Sent AI command: \"${payload.optString("prompt")}\"")
            "power_command" -> addLog("Sent power action: ${payload.optString("action").uppercase()}")
            "launch_app" -> addLog("Requesting app launch: \"${payload.optString("app_name")}\"")
            else -> addLog("Sent request action: $type")
        }
    }

    fun disconnect() {
        addLog("Disconnecting secure session.")
        client?.disconnect()
        client = null
    }

    fun setLogsSubscription(enable: Boolean) {
        val payload = JSONObject().apply { put("enable", enable) }
        sendMessage("subscribe_logs", payload)
    }
}
