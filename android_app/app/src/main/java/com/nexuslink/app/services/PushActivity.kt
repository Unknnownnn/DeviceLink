package com.nexuslink.app.services

import androidx.activity.ComponentActivity
import android.os.Bundle
import android.widget.Toast
import com.nexuslink.app.network.ConnectionManager
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

@AndroidEntryPoint
class PushActivity : ComponentActivity() {

    @Inject
    lateinit var connectionManager: ConnectionManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Do not finish here; wait for onWindowFocusChanged
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            // Now that we have window focus, Android 10+ allows us to read the clipboard!
            connectionManager.pushClipboardToPc()
            
            Toast.makeText(this, "Pushed clipboard to PC", Toast.LENGTH_SHORT).show()
            
            // Finish the activity immediately after reading
            finish()
        }
    }
}
