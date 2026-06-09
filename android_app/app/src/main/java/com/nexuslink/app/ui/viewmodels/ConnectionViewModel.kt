package com.nexuslink.app.ui.viewmodels

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.TrustedPeer
import com.nexuslink.app.network.ConnectionManager
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.network.FileTransferManager
import com.nexuslink.app.network.NexusWebSocketClient
import com.nexuslink.app.network.SessionEvent
import com.nexuslink.app.services.NexusForegroundService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject

private const val TAG = "ConnectionViewModel"

data class ConnectionUiState(
    val connectionState: ConnectionState = ConnectionState.Disconnected,
    val pingCount: Int = 0,
    val pongCount: Int = 0,
    val lastPongPayload: String = "",
    val lastClipboardSync: String = "",
    val errorMessage: String? = null,
)

/**
 * ViewModel for the active connection screen.
 *
 * Owns the [NexusWebSocketClient] lifecycle and exposes:
 * - [uiState] for screen rendering
 * - [toastEvents] for one-shot user notifications
 */
@HiltViewModel
class ConnectionViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val connectionManager: ConnectionManager,
    private val fileTransferManager: FileTransferManager
) : ViewModel() {

    val uiState = connectionManager.uiState
    val toastEvents = connectionManager.toastEvents
    val nlpResponses = connectionManager.nlpResponses
    val deckShortcuts = connectionManager.deckShortcuts

    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        connectionManager.pushClipboardToPc()
    }

    init {
        clipboardManager.addPrimaryClipChangedListener(clipboardListener)
    }

    fun connect(host: String, port: Int, peerFingerprint: String) {
        // Start foreground service to hold the connection
        val intent = Intent(context, NexusForegroundService::class.java).apply {
            action = NexusForegroundService.ACTION_START
        }
        ContextCompat.startForegroundService(context, intent)

        connectionManager.connect(host, port, peerFingerprint)
    }

    fun sendPing() {
        connectionManager.sendPing()
    }

    fun pushClipboardToPc() {
        connectionManager.pushClipboardToPc()
    }

    fun sendNlpCommand(prompt: String) {
        val payload = org.json.JSONObject().apply { put("prompt", prompt) }
        connectionManager.sendMessage("nlp_command", payload)
        viewModelScope.launch { connectionManager.emitToast("Sending AI command...") }
    }

    fun sendPowerCommand(action: String) {
        val payload = org.json.JSONObject().apply { put("action", action) }
        connectionManager.sendMessage("power_command", payload)
        viewModelScope.launch { connectionManager.emitToast("Sending $action command...") }
    }

    fun launchApp(appName: String) {
        val payload = org.json.JSONObject().apply { put("app_name", appName) }
        connectionManager.sendMessage("launch_app", payload)
        viewModelScope.launch { connectionManager.emitToast("Launching $appName...") }
    }

    fun sendFile(uri: Uri) {
        fileTransferManager.sendFile(uri)
        viewModelScope.launch { connectionManager.emitToast("Sending file to PC...") }
    }

    fun disconnect() {
        // Stop foreground service
        val intent = Intent(context, NexusForegroundService::class.java).apply {
            action = NexusForegroundService.ACTION_STOP
        }
        ContextCompat.startForegroundService(context, intent)
    }

    override fun onCleared() {
        super.onCleared()
        clipboardManager.removePrimaryClipChangedListener(clipboardListener)
        // Note: we do NOT disconnect the client onCleared because we want
        // the connection to persist in the background Foreground Service.
    }
}
