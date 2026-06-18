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
import com.nexuslink.app.services.BluetoothHFPManager
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
import org.json.JSONArray

private const val TAG = "ConnectionViewModel"

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
    val bluetoothConnected = connectionManager.bluetoothConnected
    val desktopDeck = connectionManager.desktopDeck
    val launchConsentRequest = connectionManager.launchConsentRequest




    private val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        connectionManager.pushClipboardToPc()
    }

    private val _aiChatHistory = MutableStateFlow<List<ChatMessage>>(emptyList())
    val aiChatHistory: StateFlow<List<ChatMessage>> = _aiChatHistory

    var lastNlpPrompt: String? = null
        private set

    init {
        clipboardManager.addPrimaryClipChangedListener(clipboardListener)
        _aiChatHistory.value = loadChatHistory()
        viewModelScope.launch {
            nlpResponses.collect { response ->
                val prompt = lastNlpPrompt ?: "AI Command"
                val newMsg = ChatMessage(prompt, response)
                _aiChatHistory.update { current ->
                    val updated = current + newMsg
                    val limited = if (updated.size > 30) updated.takeLast(30) else updated
                    saveChatHistory(limited)
                    limited
                }
            }
        }
    }

    private fun saveChatHistory(history: List<ChatMessage>) {
        try {
            val prefs = context.getSharedPreferences("ai_chat_prefs", Context.MODE_PRIVATE)
            val jsonArray = JSONArray()
            for (msg in history) {
                val obj = JSONObject().apply {
                    put("prompt", msg.prompt)
                    put("response", msg.response)
                    put("timestamp", msg.timestamp)
                }
                jsonArray.put(obj)
            }
            prefs.edit().putString("chat_history", jsonArray.toString()).apply()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save chat history: ${e.message}")
        }
    }

    private fun loadChatHistory(): List<ChatMessage> {
        val prefs = context.getSharedPreferences("ai_chat_prefs", Context.MODE_PRIVATE)
        val historyStr = prefs.getString("chat_history", null) ?: return emptyList()
        val history = mutableListOf<ChatMessage>()
        try {
            val jsonArray = JSONArray(historyStr)
            for (i in 0 until jsonArray.length()) {
                val obj = jsonArray.getJSONObject(i)
                history.add(
                    ChatMessage(
                        prompt = obj.getString("prompt"),
                        response = obj.getString("response"),
                        timestamp = obj.optLong("timestamp", System.currentTimeMillis())
                    )
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to load chat history: ${e.message}")
        }
        return history
    }

    fun connect(host: String, port: Int, peerFingerprint: String) {
        // Start foreground service to hold the connection
        val intent = Intent(context, NexusForegroundService::class.java).apply {
            action = NexusForegroundService.ACTION_START
        }
        ContextCompat.startForegroundService(context, intent)

        connectionManager.connect(host, port, peerFingerprint)
    }

    fun pushClipboardToPc() {
        connectionManager.pushClipboardToPc()
    }

    fun sendNlpCommand(prompt: String) {
        lastNlpPrompt = prompt
        val payload = org.json.JSONObject().apply { put("prompt", prompt) }
        connectionManager.sendMessage("nlp_command", payload)
        viewModelScope.launch { connectionManager.emitToast("Sending AI command...") }
    }

    fun retryLastNlpCommand() {
        val prompt = lastNlpPrompt ?: return
        sendNlpCommand(prompt)
    }

    fun clearChatHistory() {
        _aiChatHistory.value = emptyList()
        saveChatHistory(emptyList())
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
        connectionManager.addLog("Sending file to PC: ${uri.lastPathSegment ?: "file"}")
        viewModelScope.launch { connectionManager.emitToast("Sending file to PC...") }
    }

    fun disconnect() {
        // Stop foreground service
        val intent = Intent(context, NexusForegroundService::class.java).apply {
            action = NexusForegroundService.ACTION_STOP
        }
        ContextCompat.startForegroundService(context, intent)
    }

    fun setLogsSubscription(enable: Boolean) {
        connectionManager.setLogsSubscription(enable)
    }

    fun saveDesktopDeckApps(apps: List<org.json.JSONObject>) {
        connectionManager.saveDesktopDeckApps(apps)
    }

    fun respondToLaunchConsent(consentId: String, approved: Boolean) {
        connectionManager.respondToLaunchConsent(consentId, approved)
    }

    override fun onCleared() {
        super.onCleared()
        clipboardManager.removePrimaryClipChangedListener(clipboardListener)
        // Note: we do NOT disconnect the client onCleared because we want
        // the connection to persist in the background Foreground Service.
    }
}

data class ChatMessage(
    val prompt: String,
    val response: String,
    val timestamp: Long = System.currentTimeMillis()
)
