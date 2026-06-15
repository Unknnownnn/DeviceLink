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
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.DatagramSocket
import java.net.InetSocketAddress
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ConnectionManager"

data class ConnectionUiState(
    val connectionState: ConnectionState = ConnectionState.Disconnected,
    val host: String = "",
    val port: Int = 0,
    val peerFingerprint: String? = null,
    val lastClipboardSync: String = "",
    val errorMessage: String? = null,
    val logs: List<String> = emptyList(),
    val connectionPhase: String = "",
)

@Singleton
class ConnectionManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val identity: IdentityManager,
    private val peerStore: PeerStore,
    private val discoveryManager: NsdDiscoveryManager,
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
    private var udpClient: NexusUdpClient? = null
    private var firebaseRelay: FirebaseRelay? = null
    private var connectJob: kotlinx.coroutines.Job? = null
    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private var lastClipboardSent = ""
    private var lastSeenPcTime = 0L
    private var heartbeatJob: kotlinx.coroutines.Job? = null

    private fun stopFirebaseRelay(notifyCloudDisconnect: Boolean = false) {
        val relay = firebaseRelay ?: return

        if (notifyCloudDisconnect) {
            runCatching {
                val payload = JSONObject().apply {
                    put("reason", "android_disconnected")
                }
                val message = JSONObject().apply {
                    put("type", "cloud_disconnect")
                    put("id", java.util.UUID.randomUUID().toString())
                    put("payload", payload)
                }
                relay.sendMessage(message.toString().toByteArray(Charsets.UTF_8))
            }.onFailure {
                Log.w(TAG, "Failed to notify cloud relay disconnect", it)
            }
        }

        relay.stopListening()
        firebaseRelay = null
    }

    init {
        // Register this manager so non-Hilt singletons can send WebSocket messages
        ConnManagerProxy.register(this)
        // Initial Bluetooth state check
        CallBridgeManager.refreshBluetoothState(context)
    }

    fun addLog(message: String) {
        Log.i(TAG, message)
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
        connectJob?.cancel()
        if (client != null || udpClient != null) {
            disconnect()
        }

        _uiState.update { it.copy(
            host = host, 
            port = port,
            peerFingerprint = peerFingerprint,
            errorMessage = null,
            connectionState = ConnectionState.Connecting,
            connectionPhase = "Initiating connection...",
            logs = emptyList() // Clear logs on new connection
        ) }
        lastSeenPcTime = System.currentTimeMillis()

        addLog("Connecting to secure agent...")

        connectJob = scope.launch {
            // Stage 1: Try Local Connection (mDNS/WebSocket)
            var localSuccess = false
            var targetHost = host
            var targetPort = port

            if (targetHost.equals("cloud", ignoreCase = true)) {
                _uiState.update { it.copy(connectionPhase = "Stage 1: Scanning local network via mDNS") }
                addLog("Stage 1: Device is listed as Cloud. Scanning local network for mDNS endpoint")
                try {
                    kotlinx.coroutines.withTimeout(2500) {
                        discoveryManager.discoverDevices().collect { devices ->
                            val match = devices.find { it.fingerprint == peerFingerprint }
                            if (match != null) {
                                targetHost = match.host
                                targetPort = match.port
                                addLog("mDNS resolved local target: $targetHost:$targetPort")
                                throw Exception("MATCH_FOUND")
                            }
                        }
                    }
                } catch (e: Exception) {
                    if (e.message != "MATCH_FOUND") {
                        addLog("mDNS scan completed (no local matching device found).")
                    }
                }
            }

            if (!targetHost.equals("cloud", ignoreCase = true)) {
                _uiState.update { it.copy(connectionPhase = "Stage 1: Connecting to local agent via mDNS") }
                addLog("Stage 1: Attempting local mDNS connection to $targetHost:$targetPort...")
                val wsClient = NexusWebSocketClient(
                    host = targetHost,
                    port = targetPort,
                    identity = identity,
                    peerFingerprint = peerFingerprint,
                    scope = scope
                )
                client = wsClient
                
                val wsStateJob = launch {
                    wsClient.state.collect { state ->
                        _uiState.update { it.copy(connectionState = state) }
                        if (state is ConnectionState.Connected) {
                            localSuccess = true
                        }
                    }
                }
                
                val wsEventJob = launch {
                    for (event in wsClient.events) {
                        recordActivity()
                        when (event) {
                            is SessionEvent.SessionEstablished -> {
                                addLog("Secure mDNS session established: ${event.deviceName}")
                                val existingPeer = peerStore.getPeer(peerFingerprint)
                                if (existingPeer == null || existingPeer.displayName != event.deviceName) {
                                    peerStore.addPeer(TrustedPeer(
                                        fingerprint = peerFingerprint,
                                        ed25519PublicKeyB64 = event.peerEd25519PubB64,
                                        displayName = event.deviceName,
                                    ))
                                }
                            }
                            is SessionEvent.MessageReceived -> handleMessageReceived(event)
                            is SessionEvent.ClipboardUpdate -> {
                                val text = event.text
                                if (text.isNotBlank() && text != lastClipboardSent) {
                                    lastClipboardSent = text
                                    _uiState.update { it.copy(lastClipboardSync = text) }
                                    addLog("Received clipboard sync from PC")
                                    _clipboardUpdates.emit(text)
                                }
                            }
                            else -> {}
                        }
                    }
                }
                
                wsClient.connect()
                
                // Wait up to 6 seconds
                for (i in 0 until 60) {
                    if (localSuccess) break
                    delay(100)
                }
                
                if (localSuccess) {
                    addLog("Stage 1 success: connected via mDNS!")
                    return@launch
                } else {
                    addLog("Stage 1 failed or timed out. Cleaning up WS client...")
                    wsStateJob.cancel()
                    wsEventJob.cancel()
                    wsClient.disconnect()
                    client = null
                }
            }
            
            // Stage 2: Try STUN / UDP Hole Punching
            _uiState.update { it.copy(connectionPhase = "Stage 2: Initiating STUN UDP hole punching...") }
            addLog("Stage 2: Attempting STUN with UDP hole punching...")
            
            stopFirebaseRelay()
            val signalReceived = kotlinx.coroutines.channels.Channel<JSONObject>(kotlinx.coroutines.channels.Channel.BUFFERED)
            val relay = FirebaseRelay(peerFingerprint, scope) { jsonStr ->
                recordActivity()
                scope.launch {
                    try {
                        val json = JSONObject(jsonStr)
                        val type = json.optString("type")
                        val payload = json.optJSONObject("payload") ?: JSONObject()
                        
                        if (type == "stun_response") {
                            signalReceived.send(payload)
                        } else {
                            handleMessageReceived(SessionEvent.MessageReceived(type, payload))
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Failed to parse firebase message", e)
                    }
                }
            }
            firebaseRelay = relay
            relay.startListening()
            
            val udp = NexusUdpClient(identity, peerFingerprint, scope)
            udpClient = udp
            
            val localIp = udp.getLocalIp()
            val localPort = 47201
            
            var stunSuccess = false
            var stunAddr: InetSocketAddress? = null
            
            try {
                _uiState.update { it.copy(connectionPhase = "Stage 2: Querying STUN server") }
                addLog("Querying STUN server (stun.l.google.com)...")
                stunAddr = udp.queryStun(localPort)
                
                if (stunAddr != null) {
                    stunSuccess = true
                    addLog("STUN resolved public IP: ${stunAddr.address?.hostAddress ?: stunAddr.hostString}:${stunAddr.port}")
                } else {
                    addLog("STUN query timed out. Proceeding with local IP as public endpoint.")
                }
            } catch (e: Exception) {
                addLog("STUN binding/query error: ${e.message}")
            }
            
            val publicIp = stunAddr?.address?.hostAddress ?: stunAddr?.hostString ?: localIp
            val publicPort = stunAddr?.port ?: localPort
            
            val initPayload = JSONObject().apply {
                put("local_ip", localIp)
                put("local_port", localPort)
                put("public_ip", publicIp)
                put("public_port", publicPort)
            }
            
            val stunInitMsg = JSONObject().apply {
                put("type", "stun_initiate")
                put("id", java.util.UUID.randomUUID().toString())
                put("payload", initPayload)
            }
            
            _uiState.update { it.copy(connectionPhase = "Stage 2: Exchanging connection candidates") }
            addLog("Sending candidates to PC via Cloud Relay...")
            relay.sendMessage(stunInitMsg.toString().toByteArray(Charsets.UTF_8))
            
            var stunResponsePayload: JSONObject? = null
            try {
                kotlinx.coroutines.withTimeout(10000) {
                    stunResponsePayload = signalReceived.receive()
                }
            } catch (e: Exception) {
                addLog("Timed out waiting for stun_response from PC.")
            }
            
            var udpSuccess = false
            if (stunResponsePayload != null) {
                _uiState.update { it.copy(connectionPhase = "Stage 2: Punching UDP hole") }
                addLog("Received PC candidates. Punching UDP hole...")
                
                val udpStateJob = launch {
                    udp.state.collect { state ->
                        _uiState.update { it.copy(connectionState = state) }
                        if (state is ConnectionState.Connected) {
                            udpSuccess = true
                        }
                    }
                }
                
                val udpEventJob = launch {
                    for (event in udp.events) {
                        recordActivity()
                        when (event) {
                            is SessionEvent.SessionEstablished -> {
                                addLog("Secure STUN/UDP session established!")
                                val existingPeer = peerStore.getPeer(peerFingerprint)
                                if (existingPeer == null || existingPeer.displayName != event.deviceName) {
                                    peerStore.addPeer(TrustedPeer(
                                        fingerprint = peerFingerprint,
                                        ed25519PublicKeyB64 = event.peerEd25519PubB64,
                                        displayName = event.deviceName,
                                    ))
                                }
                            }
                            is SessionEvent.MessageReceived -> handleMessageReceived(event)
                            is SessionEvent.ClipboardUpdate -> {
                                val text = event.text
                                if (text.isNotBlank() && text != lastClipboardSent) {
                                    lastClipboardSent = text
                                    _uiState.update { it.copy(lastClipboardSync = text) }
                                    addLog("Received clipboard sync from PC")
                                    _clipboardUpdates.emit(text)
                                }
                            }
                            else -> {}
                        }
                    }
                }
                
                udp.startHolePunchingLoop(localIp, localPort, publicIp, publicPort, stunResponsePayload!!)
                
                for (i in 0 until 80) {
                    if (udpSuccess) break
                    delay(100)
                }
                
                if (udpSuccess) {
                    addLog("Stage 2 success: Connected directly via UDP hole punch!")
                    startHeartbeatLoop(isUdp = true)
                    return@launch
                } else {
                    addLog("Stage 2 failed: UDP connection timed out.")
                    udpStateJob.cancel()
                    udpEventJob.cancel()
                    udp.disconnect()
                    udpClient = null
                }
            } else {
                // Clean up UDP client when skipping Stage 2
                udp.disconnect()
                udpClient = null
            }
            
            // Stage 3: Fallback to Firebase Relay
            _uiState.update { it.copy(
                connectionState = ConnectionState.Connected("cloud", 0),
                connectionPhase = "Stage 3: Connected via Cloud Relay"
            ) }
            addLog("Stage 3: STUN failed. Falling back to Firebase Cloud Relay.")
            addLog("Connected securely via Cloud Relay.")
            sendMessage("request_sync", JSONObject())
            startHeartbeatLoop(isUdp = false)
        }
    }

    private suspend fun handleMessageReceived(event: SessionEvent.MessageReceived) {
        recordActivity()
        if (event.type == "pong") {
            return
        }
        if (event.type == "nlp_response") {
            val result = event.payload.optString("result", "No result")
            addLog("AI Command Result: $result")
            _nlpResponses.emit(result)
        } else if (event.type == "CLIPBOARD_UPDATE") {
            val text = event.payload.optString("text", "")
            if (text.isNotBlank() && text != lastClipboardSent) {
                lastClipboardSent = text
                _uiState.update { it.copy(lastClipboardSync = text) }
                addLog("Received clipboard sync from PC")
                _clipboardUpdates.emit(text)
            }
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
        } else if (event.type == "sync_shortcut_icon") {
            val id = event.payload.optString("id", "")
            val icon = event.payload.optString("icon", "")
            if (id.isNotBlank()) {
                val current = _deckShortcuts.value
                val updated = current.map { shortcut ->
                    if (shortcut.optString("id") == id) {
                        org.json.JSONObject(shortcut.toString()).apply {
                            put("icon", icon)
                        }
                    } else {
                        shortcut
                    }
                }
                _deckShortcuts.value = updated
            }
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
        sendMessage("CLIPBOARD_UPDATE", payload)
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
        val isConnected = _uiState.value.connectionState is ConnectionState.Connected
        if (isConnected) {
            if (client != null) {
                client?.send(type, payload)
            } else if (udpClient != null) {
                udpClient?.send(type, payload)
            } else {
                firebaseRelay?.let {
                    sendFirebaseMsg(type, payload, it)
                } ?: addLog("Not connected and no Firebase relay available.")
            }
        } else {
            firebaseRelay?.let {
                sendFirebaseMsg(type, payload, it)
            } ?: addLog("Not connected and no Firebase relay available.")
        }
        
        when (type) {
            "nlp_command" -> addLog("Sent AI command: \"${payload.optString("prompt")}\"")
            "power_command" -> addLog("Sent power action: ${payload.optString("action").uppercase()}")
            "launch_app" -> addLog("Requesting app launch: \"${payload.optString("app_name")}\"")
            else -> if (isConnected) addLog("Sent request action: $type")
        }
    }

    private fun sendFirebaseMsg(type: String, payload: JSONObject, relay: FirebaseRelay) {
        val msg = JSONObject()
        msg.put("type", type)
        msg.put("id", java.util.UUID.randomUUID().toString())
        msg.put("payload", payload)
        relay.sendMessage(msg.toString().toByteArray(Charsets.UTF_8))
        addLog("Sent message via Firebase Fallback: $type")
    }

    private fun recordActivity() {
        lastSeenPcTime = System.currentTimeMillis()
    }

    private fun startHeartbeatLoop(isUdp: Boolean) {
        heartbeatJob?.cancel()
        lastSeenPcTime = System.currentTimeMillis()
        heartbeatJob = scope.launch(Dispatchers.IO) {
            val timeoutMillis = if (isUdp) 12000L else 15000L
            while (true) {
                delay(4000)
                val isConnected = _uiState.value.connectionState is ConnectionState.Connected
                if (!isConnected) break
                
                val now = System.currentTimeMillis()
                if (now - lastSeenPcTime > timeoutMillis) {
                    addLog("Connection timed out (no response from PC for ${timeoutMillis / 1000}s).")
                    launch(Dispatchers.Main) {
                        disconnect()
                    }
                    break
                }
                
                try {
                    sendMessage("ping", JSONObject().apply { put("ping_ts", now) })
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to send heartbeat ping", e)
                }
            }
        }
    }

    fun disconnect() {
        addLog("Disconnecting secure session.")
        connectJob?.cancel()
        connectJob = null
        heartbeatJob?.cancel()
        heartbeatJob = null

        val currentConnection = _uiState.value.connectionState as? ConnectionState.Connected
        val notifyCloudDisconnect = currentConnection?.host?.equals("cloud", ignoreCase = true) == true

        if (notifyCloudDisconnect) {
            stopFirebaseRelay(notifyCloudDisconnect = true)
        } else {
            stopFirebaseRelay()
        }

        client?.disconnect()
        client = null
        
        if (udpClient != null) {
            val clientToNotify = udpClient
            scope.launch {
                try {
                    clientToNotify?.send("udp_disconnect", JSONObject())
                    delay(150)
                } catch (e: Exception) {
                    // ignore
                } finally {
                    clientToNotify?.disconnect()
                }
            }
            udpClient = null
        }

        _uiState.update {
            it.copy(
                connectionState = ConnectionState.Disconnected,
                peerFingerprint = null,
                errorMessage = null,
                connectionPhase = ""
            )
        }
    }

    fun setLogsSubscription(enable: Boolean) {
        val payload = JSONObject().apply { put("enable", enable) }
        sendMessage("subscribe_logs", payload)
    }
}
