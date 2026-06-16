package com.nexuslink.app.services

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity

/**
 * Transparent trampoline activity for background app launches.
 *
 * Android 10+ restricts starting activities from background services.
 * By routing through this transparent Activity (which immediately gains
 * window focus), we are considered "foreground" and can start any app.
 */
class LaunchAppActivity : ComponentActivity() {

    companion object {
        const val EXTRA_PACKAGE = "target_package"
        private const val TAG = "LaunchAppActivity"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        val packageName = intent.getStringExtra(EXTRA_PACKAGE) ?: ""
        if (packageName.isNotBlank()) {
            try {
                val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
                if (launchIntent != null) {
                    launchIntent.addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
                    )
                    startActivity(launchIntent)
                    Log.d(TAG, "Launched $packageName via trampoline onCreate")
                } else {
                    Log.w(TAG, "No launch intent found for $packageName")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error launching $packageName in onCreate: ${e.message}")
            }
        }
        finish()
    }
}
