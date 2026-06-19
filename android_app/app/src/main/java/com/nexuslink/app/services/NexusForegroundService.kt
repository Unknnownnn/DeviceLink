package com.nexuslink.app.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHeadset
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.nexuslink.app.MainActivity
import com.nexuslink.app.network.ConnectionManager
import com.nexuslink.app.network.ConnectionState
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class NexusForegroundService : Service() {

    @Inject
    lateinit var connectionManager: ConnectionManager

    private val serviceScope = CoroutineScope(Dispatchers.Main + Job())
    private val bluetoothReceiver = BluetoothStateReceiver()
    private var bluetoothReceiverRegistered = false

    companion object {
        const val CHANNEL_ID = "nexus_connection_channel"
        const val ACTION_START = "ACTION_START"
        const val ACTION_STOP = "ACTION_STOP"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()

        // Register Bluetooth state receiver dynamically
        try {
            val btFilter = IntentFilter().apply {
                addAction(BluetoothAdapter.ACTION_STATE_CHANGED)
                addAction(BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED)
                addAction(BluetoothDevice.ACTION_ACL_CONNECTED)
                addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED)
            }
            registerReceiver(bluetoothReceiver, btFilter)
            bluetoothReceiverRegistered = true
        } catch (e: Exception) {
            // Ignore if Bluetooth permission not yet granted
        }

        // Initialise the HFP manager (opens BluetoothHeadset profile proxy)
        BluetoothHFPManager.init(applicationContext)

        // Observe connection state to update notification
        serviceScope.launch {
            var lastState: ConnectionState? = null
            connectionManager.uiState.collect { state ->
                if (state.connectionState != lastState) {
                    lastState = state.connectionState
                    updateNotification(state.connectionState)
                    if (state.connectionState is ConnectionState.Connected) {
                        // Auto-sync contacts whenever we get a new connection
                        CallBridgeManager.syncContactsToPC(applicationContext)
                    }
                    if (state.connectionState is ConnectionState.Disconnected) {
                        stopSelf()
                    }
                }
            }
        }

        // Observe text clipboard updates to show high-priority heads-up notification
        serviceScope.launch {
            connectionManager.clipboardUpdates.collect { text ->
                showClipboardNotification(text)
            }
        }

        // Observe image clipboard updates from PC
        serviceScope.launch {
            connectionManager.clipboardImageUpdates.collect { imageB64 ->
                showClipboardImageNotification(imageB64)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                startForeground(1, buildNotification(connectionManager.uiState.value.connectionState))
            }
            ACTION_STOP -> {
                connectionManager.disconnect()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "DeviceLink Connection",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
            
            // Channel for high priority clipboard alerts
            val clipChannel = NotificationChannel(
                "nexus_clipboard_channel",
                "Clipboard Sync",
                NotificationManager.IMPORTANCE_HIGH
            )
            manager.createNotificationChannel(clipChannel)
        }
    }

    private fun updateNotification(state: ConnectionState) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(1, buildNotification(state))
    }

    private fun buildNotification(state: ConnectionState): Notification {
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra("route_to_connected", true)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val stopIntent = PendingIntent.getService(
            this, 1, Intent(this, NexusForegroundService::class.java).apply { action = ACTION_STOP },
            PendingIntent.FLAG_IMMUTABLE
        )

        val text = when (state) {
            is ConnectionState.Connected -> "Securely connected to ${state.host}"
            is ConnectionState.Handshaking -> "Performing Handshake..."
            is ConnectionState.Connecting -> "Connecting..."
            else -> "Disconnected"
        }

        val pushIntent = PendingIntent.getActivity(
            this, 3, Intent(this, PushActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            },
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("DeviceLink Active")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_secure)
            .setContentIntent(pendingIntent)
            .addAction(android.R.drawable.ic_menu_send, "Push Clipboard to PC", pushIntent)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Disconnect", stopIntent)
            .setOngoing(true)
            .build()
    }

    private fun showClipboardNotification(text: String) {
        val pasteIntent = Intent(this, PasteActivity::class.java).apply {
            putExtra("CLIPBOARD_TEXT", text)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pastePendingIntent = PendingIntent.getActivity(
            this, 2, pasteIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(this, "nexus_clipboard_channel")
            .setContentTitle("Text received from PC")
            .setContentText("Tap to paste to phone clipboard")
            .setSmallIcon(android.R.drawable.ic_menu_edit)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pastePendingIntent)
            .addAction(android.R.drawable.ic_menu_save, "Paste to Phone", pastePendingIntent)
            .setAutoCancel(true)
            .build()

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(2, notification)
    }

    private fun showClipboardImageNotification(imageB64: String) {
        val pasteIntent = Intent(this, PasteActivity::class.java).apply {
            putExtra("CLIPBOARD_IMAGE_B64", imageB64)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pastePendingIntent = PendingIntent.getActivity(
            this, 4, pasteIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(this, "nexus_clipboard_channel")
            .setContentTitle("Image received from PC")
            .setContentText("Tap to paste image to phone clipboard")
            .setSmallIcon(android.R.drawable.ic_menu_gallery)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pastePendingIntent)
            .addAction(android.R.drawable.ic_menu_save, "Paste Image", pastePendingIntent)
            .setAutoCancel(true)
            .build()

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(3, notification)
    }

    override fun onDestroy() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancel(2)
        if (bluetoothReceiverRegistered) {
            try { unregisterReceiver(bluetoothReceiver) } catch (_: Exception) {}
            bluetoothReceiverRegistered = false
        }
        BluetoothHFPManager.release()
        super.onDestroy()
    }
}
