package com.nexuslink.app.services

import android.app.Activity
import android.app.PendingIntent
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import com.nexuslink.app.network.ConnectionManager
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class DeleteConsentActivity : ComponentActivity() {

    @Inject
    lateinit var connectionManager: ConnectionManager

    private var uriStr: String? = null

    private val deleteLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { result ->
        val currentUri = uriStr
        if (currentUri != null) {
            if (result.resultCode == Activity.RESULT_OK) {
                // User approved, tell ConnectionManager to notify success
                connectionManager.notifyDeleteSuccess(currentUri)
            } else {
                // User denied or cancelled
                connectionManager.notifyDeleteFailure(currentUri, "User denied delete request")
            }
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        uriStr = intent.getStringExtra("uri")
        val pendingIntent = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra("pending_intent", PendingIntent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra("pending_intent") as? PendingIntent
        }

        if (pendingIntent != null && uriStr != null) {
            try {
                val request = IntentSenderRequest.Builder(pendingIntent.intentSender).build()
                deleteLauncher.launch(request)
            } catch (e: Exception) {
                uriStr?.let { connectionManager.notifyDeleteFailure(it, e.message ?: "Failed to launch intent sender") }
                finish()
            }
        } else {
            finish()
        }
    }
}
