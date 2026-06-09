package com.nexuslink.app.services

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import com.nexuslink.app.network.ConnectionManager
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class PasteActivity : ComponentActivity() {

    @Inject
    lateinit var connectionManager: ConnectionManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        val text = intent.getStringExtra("CLIPBOARD_TEXT")
        if (!text.isNullOrBlank()) {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("DeviceLink", text))
            
            // Also notify the ConnectionManager so it doesn't bounce it back
            connectionManager.writeToAndroidClipboard(text)
            
            Toast.makeText(this, "Pasted from PC", Toast.LENGTH_SHORT).show()
        }
        
        // Manually cancel the notification since tapping action buttons doesn't auto-cancel it
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
        notificationManager.cancel(2)
        
        // Immediately finish the transparent activity
        finish()
    }
}
