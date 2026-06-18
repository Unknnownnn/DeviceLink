package com.nexuslink.app.network

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.app.WallpaperManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.util.Base64
import java.io.ByteArrayOutputStream
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

    private val deckPrefs by lazy { context.getSharedPreferences("desktop_deck_prefs", Context.MODE_PRIVATE) }
    private val _desktopDeck = MutableStateFlow<List<org.json.JSONObject>>(emptyList())
    val desktopDeck: StateFlow<List<org.json.JSONObject>> = _desktopDeck

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
    private var statusReceiver: android.content.BroadcastReceiver? = null
    private var smsObserver: android.database.ContentObserver? = null

    private fun registerSmsObserver() {
        if (smsObserver != null) return
        smsObserver = object : android.database.ContentObserver(android.os.Handler(android.os.Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                super.onChange(selfChange)
                if (smsSyncActive) {
                    syncSmsMessages()
                }
            }
        }
        try {
            context.contentResolver.registerContentObserver(
                android.net.Uri.parse("content://sms"),
                true,
                smsObserver!!
            )
            addLog("Registered ContentObserver for SMS")
        } catch (e: Exception) {
            Log.e(TAG, "Error registering SMS ContentObserver: ${e.message}")
        }
    }

    private fun unregisterSmsObserver() {
        smsObserver?.let {
            try {
                context.contentResolver.unregisterContentObserver(it)
                addLog("Unregistered SMS ContentObserver")
            } catch (e: Exception) {
                // ignore
            }
            smsObserver = null
        }
    }

    @Volatile
    private var telemetrySyncActive = false
    @Volatile
    private var smsSyncActive = false

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
        loadDesktopDeck()
        // Force rebind Notification Listener on start to fix system unbind bug
        try {
            com.nexuslink.app.services.AppNotificationListener.tryRebind(context)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to force rebind on init: ${e.message}")
        }
    }

    private fun loadDesktopDeck() {
        val saved = deckPrefs.getString("deck_apps", "[]") ?: "[]"
        try {
            val array = org.json.JSONArray(saved)
            val list = mutableListOf<org.json.JSONObject>()
            for (i in 0 until array.length()) {
                list.add(array.getJSONObject(i))
            }
            _desktopDeck.value = list
        } catch (e: Exception) {
            Log.e(TAG, "Error loading desktop deck: ${e.message}")
        }
    }

    fun getDesktopDeckApps(): List<org.json.JSONObject> {
        return _desktopDeck.value
    }

    fun saveDesktopDeckApps(apps: List<org.json.JSONObject>) {
        _desktopDeck.value = apps
        val array = org.json.JSONArray()
        apps.forEach { array.put(it) }
        deckPrefs.edit().putString("deck_apps", array.toString()).apply()
        syncDesktopDeckWithPc()
    }

    fun syncDesktopDeckWithPc() {
        scope.launch(Dispatchers.IO) {
            val apps = getDesktopDeckApps()
            if (apps.isEmpty()) {
                sendMessage("sync_desktop_deck", org.json.JSONObject().apply {
                    put("apps", org.json.JSONArray())
                })
                return@launch
            }
            val array = org.json.JSONArray()
            apps.forEach { app ->
                val pkg = app.optString("package", "")
                val label = app.optString("label", "")
                val iconBase64 = if (pkg.isNotBlank()) getAppIconBase64(context, pkg) else ""

                val appObj = org.json.JSONObject().apply {
                    put("label", label)
                    put("package", pkg)
                    put("icon", iconBase64)
                }
                array.put(appObj)
            }
            sendMessage("sync_desktop_deck", org.json.JSONObject().apply {
                put("apps", array)
            })
            addLog("Synced ${apps.size} desktop deck apps to PC")
        }
    }

    private fun getAppIconBase64(ctx: android.content.Context, packageName: String): String {
        try {
            val pm = ctx.packageManager
            val icon = pm.getApplicationIcon(packageName)
            val src = drawableToBitmap(icon) ?: return ""

            val size = 72
            // Scale the source icon to desired size
            val scaled = android.graphics.Bitmap.createScaledBitmap(src, size, size, true)

            // Create transparent output bitmap
            val output = android.graphics.Bitmap.createBitmap(size, size, android.graphics.Bitmap.Config.ARGB_8888)
            val canvas = android.graphics.Canvas(output)

            // Draw a circular mask
            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
            canvas.drawCircle(size / 2f, size / 2f, size / 2f, paint)

            // Clip the scaled icon into the circle
            paint.xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.SRC_IN)
            canvas.drawBitmap(scaled, 0f, 0f, paint)

            val outputStream = java.io.ByteArrayOutputStream()
            output.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, outputStream)
            return android.util.Base64.encodeToString(outputStream.toByteArray(), android.util.Base64.NO_WRAP)
        } catch (e: Exception) {
            return ""
        }
    }

    private fun drawableToBitmap(drawable: android.graphics.drawable.Drawable): android.graphics.Bitmap? {
        // Always draw into a fresh ARGB_8888 bitmap to avoid operating on
        // recycled system-cache bitmaps from BitmapDrawable.getBitmap()
        val width = if (drawable.intrinsicWidth > 0) drawable.intrinsicWidth else 64
        val height = if (drawable.intrinsicHeight > 0) drawable.intrinsicHeight else 64
        val bitmap = android.graphics.Bitmap.createBitmap(width, height, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(bitmap)
        drawable.setBounds(0, 0, canvas.width, canvas.height)
        drawable.draw(canvas)
        return bitmap
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
        } else if (event.type == "request_phone_status") {
            addLog("Phone status/wallpaper request from PC")
            syncPhoneStatusAndWallpaper()
            syncDesktopDeckWithPc()
            // Always push notifications on initial connect — don't require telemetry to be active.
            // Ongoing pushes happen via AppNotificationListener.onNotificationPosted/Removed
            // which fire independently of telemetry state.
            scope.launch(Dispatchers.IO) {
                val pushed = com.nexuslink.app.services.AppNotificationListener.requestPush()
                if (!pushed) {
                    sendMessage("sync_notifications", org.json.JSONObject().apply {
                        put("error", "listener_not_bound")
                    })
                }
            }
        } else if (event.type == "telemetry_control") {
            val action = event.payload.optString("action", "")
            addLog("Telemetry control received: $action")
            if (action == "start") {
                telemetrySyncActive = true
                registerStatusReceiver()
                syncPhoneStatusAndWallpaper()
                checkAndPushNotifications()
                syncDesktopDeckWithPc()
            } else if (action == "stop") {
                telemetrySyncActive = false
                unregisterStatusReceiver()
            }
        } else if (event.type == "dismiss_notification") {
            val notifId = event.payload.optString("id", "")
            if (notifId.isNotBlank()) {
                com.nexuslink.app.services.AppNotificationListener.dismissNotification(notifId)
            }
        } else if (event.type == "start_sms_sync") {
            addLog("Starting SMS sync...")
            smsSyncActive = true
            registerSmsObserver()
            syncSmsMessages()
        } else if (event.type == "stop_sms_sync") {
            addLog("Stopping SMS sync")
            smsSyncActive = false
            unregisterSmsObserver()
        } else if (event.type == "call_action") {
            val action = event.payload.optString("action", "")
            Log.d(TAG, "call_action from PC: $action")
            addLog("Call bridge action executed: $action")
            when (action) {
                "answer" -> CallBridgeManager.answerCall(context)
                "decline" -> CallBridgeManager.declineCall(context)
                "hangup" -> CallBridgeManager.hangUpCall(context)
            }
        } else if (event.type == "android_action") {
            val action = event.payload.optString("action", "")
            Log.d(TAG, "android_action from PC: $action")
            handleAndroidAction(action, event.payload)
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

    private fun handleAndroidAction(action: String, payload: JSONObject) {
        addLog("Executing remote action: $action")
        when (action) {
            "open_notification_settings" -> {
                try {
                    val intent = Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS").apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    context.startActivity(intent)
                    addLog("Opened Notification Listener settings screen")
                } catch (e: Exception) {
                    addLog("Error opening notification settings: ${e.message}")
                }
            }
            "open_app_details" -> {
                try {
                    val intent = Intent(
                        android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        android.net.Uri.parse("package:${context.packageName}")
                    ).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
                    context.startActivity(intent)
                    addLog("Opened App details settings screen to allow restricted settings")
                } catch (e: Exception) {
                    addLog("Error opening app details settings: ${e.message}")
                }
            }
            "launch_app" -> {
                val prefs = context.getSharedPreferences("nexuslink_preferences", Context.MODE_PRIVATE)
                val isBatterySaver = prefs.getBoolean("battery_saver_enabled", false)
                val isBgLaunchEnabled = prefs.getBoolean("bg_launch_enabled", true)
                if (isBatterySaver || !isBgLaunchEnabled) {
                    addLog("Ignored app launch request: Feature is disabled in settings (Battery Saver Active)")
                    return
                }

                val appInput = (payload.optString("package_or_app_name", "").takeIf { it.isNotBlank() }
                    ?: payload.optString("package", "").takeIf { it.isNotBlank() }
                    ?: payload.optString("app_name", "").takeIf { it.isNotBlank() }
                    ?: payload.optString("name", "")).trim()
                if (appInput.isBlank()) {
                    addLog("Error: launch_app requires a valid app/package name")
                    return
                }
                
                // Map friendly names to package names
                val packageName = when (appInput.lowercase()) {
                    "whatsapp" -> "com.whatsapp"
                    "instagram" -> "com.instagram.android"
                    "youtube", "yt" -> "com.google.android.youtube"
                    "chrome" -> "com.android.chrome"
                    "facebook", "fb" -> "com.facebook.katana"
                    "spotify" -> "com.spotify.music"
                    "gmail" -> "com.google.android.gm"
                    "maps" -> "com.google.android.apps.maps"
                    else -> appInput
                }
                
                try {
                    val activeContext = com.nexuslink.app.services.AppNotificationListener.instance ?: context
                    val hasOverlay = android.provider.Settings.canDrawOverlays(activeContext)
                    addLog("App launch requested: packageName=$packageName, isBatterySaver=$isBatterySaver, isBgLaunchEnabled=$isBgLaunchEnabled, hasOverlay=$hasOverlay")
                    if (isBatterySaver || !isBgLaunchEnabled) {
                        addLog("Ignored app launch request: Feature is disabled in settings (Battery Saver Active or background launch disabled)")
                        return
                    }

                    // Always route through the transparent trampoline activity LaunchAppActivity.
                    // This is essential on Android 10+ because starting the target app directly 
                    // from a background service is blocked by the OS as a background cross-app launch.
                    // Starting our own windowed activity (LaunchAppActivity) is allowed if overlay 
                    // permission is granted, which then starts the target app from the foreground.
                    val launchIntent = Intent(activeContext, com.nexuslink.app.services.LaunchAppActivity::class.java).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                        putExtra(com.nexuslink.app.services.LaunchAppActivity.EXTRA_PACKAGE, packageName)
                    }
                    
                    if (!hasOverlay) {
                        addLog("Warning: 'Display over other apps' overlay permission is not granted. Background activity starts may be blocked by Android.")
                    }

                    activeContext.startActivity(launchIntent)
                    addLog("Launched app: $packageName via LaunchAppActivity trampoline (startActivity)")
                } catch (e: Exception) {
                    addLog("Direct launch via trampoline failed: ${e.message}, attempting PendingIntent fallback...")
                    try {
                        val activeContext = com.nexuslink.app.services.AppNotificationListener.instance ?: context
                        val launchIntent = Intent(activeContext, com.nexuslink.app.services.LaunchAppActivity::class.java).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                            putExtra(com.nexuslink.app.services.LaunchAppActivity.EXTRA_PACKAGE, packageName)
                        }
                        
                        if (android.os.Build.VERSION.SDK_INT >= 34) {
                            val options = android.app.ActivityOptions.makeBasic().apply {
                                setPendingIntentBackgroundActivityStartMode(android.app.ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED)
                            }
                            val pendingIntent = android.app.PendingIntent.getActivity(
                                activeContext,
                                0,
                                launchIntent,
                                android.app.PendingIntent.FLAG_MUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT
                            )
                            pendingIntent.send(activeContext, 0, null, null, null, null, options.toBundle())
                        } else {
                            val pendingIntent = android.app.PendingIntent.getActivity(
                                activeContext,
                                0,
                                launchIntent,
                                (if (android.os.Build.VERSION.SDK_INT >= 23) android.app.PendingIntent.FLAG_IMMUTABLE else 0) or android.app.PendingIntent.FLAG_UPDATE_CURRENT
                            )
                            pendingIntent.send()
                        }
                        addLog("Launched app: $packageName via LaunchAppActivity PendingIntent fallback")
                    } catch (ex: Exception) {
                        addLog("Fallback launch failed: ${ex.message}")
                    }
                }
            }
            "toggle_torch" -> {
                val state = payload.optBoolean("state", false) ||
                            payload.optString("state", "").lowercase() in listOf("true", "on", "yes", "1")
                val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                try {
                    val cameraId = cameraManager.cameraIdList.firstOrNull()
                    if (cameraId != null) {
                        cameraManager.setTorchMode(cameraId, state)
                        addLog("Flashlight toggled to: ${if (state) "ON" else "OFF"}")
                    } else {
                        addLog("Error toggling flashlight: No camera found")
                    }
                } catch (e: Exception) {
                    addLog("Error toggling flashlight: ${e.message}")
                }
            }
            "volume_control" -> {
                val streamTypeStr = payload.optString("stream", "media")
                val volumeLevel = payload.optInt("volume_level", -1).takeIf { it != -1 }
                    ?: payload.optInt("level", -1).takeIf { it != -1 }
                    ?: payload.optInt("volume", -1)
                
                val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                val streamType = when (streamTypeStr.lowercase()) {
                    "ring" -> AudioManager.STREAM_RING
                    else -> AudioManager.STREAM_MUSIC
                }
                
                try {
                    val maxVolume = audioManager.getStreamMaxVolume(streamType)
                    if (volumeLevel in 0..100) {
                        val targetVolume = (maxVolume * (volumeLevel / 100.0)).toInt()
                        audioManager.setStreamVolume(streamType, targetVolume, AudioManager.FLAG_SHOW_UI)
                        addLog("Set $streamTypeStr volume to $volumeLevel% ($targetVolume/$maxVolume)")
                    } else {
                        addLog("Error: volume_level ($volumeLevel) must be between 0 and 100")
                    }
                } catch (e: Exception) {
                    addLog("Error setting volume: ${e.message}")
                }
            }
            "set_ringer_mode" -> {
                val mode = payload.optString("mode", "normal")
                val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                try {
                    val ringerMode = when (mode.lowercase()) {
                        "silent" -> AudioManager.RINGER_MODE_SILENT
                        "vibrate" -> AudioManager.RINGER_MODE_VIBRATE
                        else -> AudioManager.RINGER_MODE_NORMAL
                    }
                    audioManager.ringerMode = ringerMode
                    addLog("Ringer mode set to: $mode")
                } catch (e: Exception) {
                    addLog("Error setting ringer mode: ${e.message}")
                }
            }
            "set_vibrate" -> {
                val state = payload.optBoolean("state", false)
                val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                try {
                    if (state) {
                        // Switch to vibrate mode if currently normal/silent
                        audioManager.ringerMode = AudioManager.RINGER_MODE_VIBRATE
                    } else {
                        // Turn off vibrate — restore normal
                        audioManager.ringerMode = AudioManager.RINGER_MODE_NORMAL
                    }
                    addLog("Vibrate set to: $state")
                } catch (e: Exception) {
                    addLog("Error setting vibrate: ${e.message}")
                }
            }
            "set_dnd" -> {
                val state = payload.optBoolean("state", false)
                try {
                    val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                    if (nm.isNotificationPolicyAccessGranted) {
                        val filter = if (state) {
                            android.app.NotificationManager.INTERRUPTION_FILTER_NONE
                        } else {
                            android.app.NotificationManager.INTERRUPTION_FILTER_ALL
                        }
                        nm.setInterruptionFilter(filter)
                        addLog("DND set to: $state")
                    } else {
                        addLog("DND: Notification Policy access not granted — opening settings")
                        val intent = Intent(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        context.startActivity(intent)
                    }
                } catch (e: Exception) {
                    addLog("Error setting DND: ${e.message}")
                }
            }
            "set_airplane_mode" -> {
                // Airplane mode requires WRITE_SECURE_SETTINGS (system permission) on Android 4.2+.
                // Best we can do without root is open the network settings so the user can toggle it.
                addLog("Airplane mode: opening network settings (system restriction)")
                try {
                    val intent = Intent(android.provider.Settings.ACTION_AIRPLANE_MODE_SETTINGS).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                    context.startActivity(intent)
                } catch (e: Exception) {
                    addLog("Error opening airplane settings: ${e.message}")
                }
            }
            else -> {
                addLog("Unknown remote Android action: $action")
            }
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
        telemetrySyncActive = false
        smsSyncActive = false
        unregisterStatusReceiver()
        unregisterSmsObserver()
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

    fun syncPhoneStatusAndWallpaper() {
        if (!telemetrySyncActive) return
        val prefs = context.getSharedPreferences("nexuslink_preferences", Context.MODE_PRIVATE)
        val isBatterySaver = prefs.getBoolean("battery_saver_enabled", false)
        val isPhoneSyncEnabled = prefs.getBoolean("phone_sync_enabled", true)
        if (isBatterySaver || !isPhoneSyncEnabled) {
            return
        }

        scope.launch(Dispatchers.IO) {
            try {
                val payload = JSONObject()
                
                // 1. Get audio/ringer status
                try {
                    val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                    val ringerMode = when (audioManager.ringerMode) {
                        AudioManager.RINGER_MODE_SILENT -> "silent"
                        AudioManager.RINGER_MODE_VIBRATE -> "vibrate"
                        AudioManager.RINGER_MODE_NORMAL -> "normal"
                        else -> "unknown"
                    }
                    payload.put("ringer_mode", ringerMode)
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting ringer mode: ${e.message}")
                    payload.put("ringer_mode", "unknown")
                }
                
                // 2. Get DND status
                try {
                    val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                    val dndEnabled = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                        notificationManager.currentInterruptionFilter != android.app.NotificationManager.INTERRUPTION_FILTER_ALL
                    } else {
                        false
                    }
                    payload.put("dnd_enabled", dndEnabled)
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting DND status: ${e.message}")
                    payload.put("dnd_enabled", false)
                }
                
                // 3. Get Airplane Mode
                try {
                    val airplaneMode = android.provider.Settings.Global.getInt(
                        context.contentResolver,
                        android.provider.Settings.Global.AIRPLANE_MODE_ON, 0
                    ) != 0
                    payload.put("airplane_mode", airplaneMode)
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting airplane mode: ${e.message}")
                    payload.put("airplane_mode", false)
                }
                
                // 4. Get Battery Status
                try {
                    val batteryStatus: Intent? = context.registerReceiver(
                        null,
                        android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED)
                    )
                    val batteryLevel = batteryStatus?.let { intent ->
                        val level = intent.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1)
                        val scale = intent.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1)
                        if (level >= 0 && scale > 0) (level * 100 / scale.toFloat()).toInt() else 100
                    } ?: 100
                    val isCharging = batteryStatus?.let { intent ->
                        val status = intent.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1)
                        status == android.os.BatteryManager.BATTERY_STATUS_CHARGING ||
                                status == android.os.BatteryManager.BATTERY_STATUS_FULL
                    } ?: false
                    
                    payload.put("battery_level", batteryLevel)
                    payload.put("is_charging", isCharging)
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting battery status: ${e.message}")
                    payload.put("battery_level", 100)
                    payload.put("is_charging", false)
                }
                
                // 5. Get Wallpaper Dominant Colors
                try {
                    val wallpaperManager = WallpaperManager.getInstance(context)
                    if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O_MR1) {
                        val colors = wallpaperManager.getWallpaperColors(WallpaperManager.FLAG_SYSTEM)
                        if (colors != null) {
                            val primaryHex = String.format("#%06X", 0xFFFFFF and colors.primaryColor.toArgb())
                            payload.put("primary_color", primaryHex)
                            
                            val secondaryHex = colors.secondaryColor?.let { 
                                String.format("#%06X", 0xFFFFFF and it.toArgb()) 
                            } ?: ""
                            payload.put("secondary_color", secondaryHex)

                            val tertiaryHex = colors.tertiaryColor?.let { 
                                String.format("#%06X", 0xFFFFFF and it.toArgb()) 
                            } ?: ""
                            payload.put("tertiary_color", tertiaryHex)
                        } else {
                            payload.put("primary_color", "")
                            payload.put("secondary_color", "")
                            payload.put("tertiary_color", "")
                        }
                    } else {
                        payload.put("primary_color", "")
                        payload.put("secondary_color", "")
                        payload.put("tertiary_color", "")
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error getting wallpaper colors: ${e.message}")
                    payload.put("primary_color", "")
                    payload.put("secondary_color", "")
                    payload.put("tertiary_color", "")
                }
                
                addLog("Sending phone status and dominant colors to PC...")
                sendMessage("sync_phone_status", payload)
            } catch (e: Exception) {
                addLog("Error syncing phone status: ${e.message}")
            }
        }
    }

    private fun isNotificationServiceEnabled(context: Context): Boolean {
        val pkgName = context.packageName
        val flat = android.provider.Settings.Secure.getString(
            context.contentResolver,
            "enabled_notification_listeners"
        )
        return flat != null && flat.contains(pkgName)
    }

    fun checkAndPushNotifications() {
        if (!telemetrySyncActive) return
        if (isNotificationServiceEnabled(context)) {
            val success = com.nexuslink.app.services.AppNotificationListener.requestPush()
            if (!success) {
                addLog("Notification listener not active/bound by OS. Try toggling Notification Access off/on.")
                sendMessage("sync_notifications", org.json.JSONObject().apply {
                    put("error", "listener_not_bound")
                })
            }
        } else {
            sendMessage("sync_notifications", org.json.JSONObject().apply {
                put("error", "permission_denied")
            })
        }
    }

    fun syncSmsMessages() {
        if (!smsSyncActive) return
        scope.launch(Dispatchers.IO) {
            try {
                if (androidx.core.content.ContextCompat.checkSelfPermission(
                        context,
                        android.Manifest.permission.READ_SMS
                    ) != android.content.pm.PackageManager.PERMISSION_GRANTED
                ) {
                    addLog("SMS permission not granted. Sending error to PC...")
                    sendMessage("sync_sms", JSONObject().apply {
                        put("error", "permission_denied")
                    })
                    return@launch
                }

                val smsUri = android.net.Uri.parse("content://sms/inbox")
                val cursor = context.contentResolver.query(
                    smsUri,
                    arrayOf("_id", "address", "body", "date", "read"),
                    null,
                    null,
                    "date DESC LIMIT 30"
                )
                val array = org.json.JSONArray()
                cursor?.use { c ->
                    val idCol = c.getColumnIndex("_id")
                    val addressCol = c.getColumnIndex("address")
                    val bodyCol = c.getColumnIndex("body")
                    val dateCol = c.getColumnIndex("date")
                    val readCol = c.getColumnIndex("read")
                    while (c.moveToNext()) {
                        val item = JSONObject().apply {
                            put("id", if (idCol >= 0) c.getString(idCol) else "")
                            put("sender", if (addressCol >= 0) c.getString(addressCol) else "Unknown")
                            put("body", if (bodyCol >= 0) c.getString(bodyCol) else "")
                            put("date", if (dateCol >= 0) c.getLong(dateCol) else 0L)
                            put("read", if (readCol >= 0) c.getInt(readCol) == 1 else true)
                        }
                        array.put(item)
                    }
                }
                sendMessage("sync_sms", JSONObject().apply {
                    put("messages", array)
                })
                addLog("Synced ${array.length()} SMS messages to PC.")
            } catch (e: Exception) {
                Log.e(TAG, "Error syncing SMS messages: ${e.message}")
            }
        }
    }

    private fun registerStatusReceiver() {
        if (statusReceiver != null) return
        val filter = android.content.IntentFilter().apply {
            addAction(AudioManager.RINGER_MODE_CHANGED_ACTION)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                addAction(android.app.NotificationManager.ACTION_INTERRUPTION_FILTER_CHANGED)
            }
            addAction(Intent.ACTION_AIRPLANE_MODE_CHANGED)
            addAction(Intent.ACTION_BATTERY_CHANGED)
        }
        statusReceiver = object : android.content.BroadcastReceiver() {
            private var lastBatteryLevel = -1
            private var lastIsCharging = false
            private var lastRingerMode = ""
            private var lastDndEnabled = false
            private var lastAirplaneMode = false

            override fun onReceive(context: Context, intent: Intent) {
                if (!telemetrySyncActive) return
                var changed = false
                val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                val ringerMode = when (audioManager.ringerMode) {
                    AudioManager.RINGER_MODE_SILENT -> "silent"
                    AudioManager.RINGER_MODE_VIBRATE -> "vibrate"
                    AudioManager.RINGER_MODE_NORMAL -> "normal"
                    else -> "unknown"
                }
                if (ringerMode != lastRingerMode) {
                    lastRingerMode = ringerMode
                    changed = true
                }

                val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                val dndEnabled = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                    notificationManager.currentInterruptionFilter != android.app.NotificationManager.INTERRUPTION_FILTER_ALL
                } else {
                    false
                }
                if (dndEnabled != lastDndEnabled) {
                    lastDndEnabled = dndEnabled
                    changed = true
                }

                val airplaneMode = android.provider.Settings.Global.getInt(
                    context.contentResolver,
                    android.provider.Settings.Global.AIRPLANE_MODE_ON, 0
                ) != 0
                if (airplaneMode != lastAirplaneMode) {
                    lastAirplaneMode = airplaneMode
                    changed = true
                }

                if (intent.action == Intent.ACTION_BATTERY_CHANGED) {
                    val level = intent.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1)
                    val scale = intent.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1)
                    val batteryLevel = if (level >= 0 && scale > 0) (level * 100 / scale.toFloat()).toInt() else 100
                    val status = intent.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1)
                    val isCharging = status == android.os.BatteryManager.BATTERY_STATUS_CHARGING ||
                            status == android.os.BatteryManager.BATTERY_STATUS_FULL
                    
                    if (batteryLevel != lastBatteryLevel || isCharging != lastIsCharging) {
                        lastBatteryLevel = batteryLevel
                        lastIsCharging = isCharging
                        changed = true
                    }
                }

                if (changed) {
                    Log.d("ConnectionManager", "Phone status changed. Syncing status and colors...")
                    syncPhoneStatusAndWallpaper()
                }
            }
        }
        context.registerReceiver(statusReceiver, filter)
        Log.i("ConnectionManager", "Registered dynamic statusReceiver for real-time Phone settings sync")
    }

    private fun unregisterStatusReceiver() {
        statusReceiver?.let {
            try {
                context.unregisterReceiver(it)
                Log.i("ConnectionManager", "Unregistered statusReceiver cleanly")
            } catch (e: Exception) {
                // ignore
            }
            statusReceiver = null
        }
    }
}

