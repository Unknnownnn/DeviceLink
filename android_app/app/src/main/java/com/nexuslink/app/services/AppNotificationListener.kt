package com.nexuslink.app.services

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

class AppNotificationListener : NotificationListenerService() {
    companion object {
        private const val TAG = "NotificationListener"
        
        @Volatile
        var instance: AppNotificationListener? = null

        fun dismissNotification(key: String) {
            val inst = instance
            if (inst != null) {
                try {
                    inst.cancelNotification(key)
                    Log.i(TAG, "Dismissed notification with key: $key")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to dismiss notification: ${e.message}")
                }
            } else {
                Log.w(TAG, "Cannot dismiss notification: Listener instance is null")
            }
        }
        
        fun requestPush(): Boolean {
            val inst = instance
            if (inst != null) {
                inst.pushActiveNotifications()
                return true
            }
            return false
        }

        fun tryRebind(context: android.content.Context) {
            try {
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.N) {
                    val componentName = android.content.ComponentName(context, AppNotificationListener::class.java)
                    requestRebind(componentName)
                    Log.i(TAG, "Requested rebind for NotificationListener")
                } else {
                    val pm = context.packageManager
                    val componentName = android.content.ComponentName(context, AppNotificationListener::class.java)
                    pm.setComponentEnabledSetting(
                        componentName,
                        android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                        android.content.pm.PackageManager.DONT_KILL_APP
                    )
                    pm.setComponentEnabledSetting(
                        componentName,
                        android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                        android.content.pm.PackageManager.DONT_KILL_APP
                    )
                    Log.i(TAG, "Toggled component state to force rebind")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error trying to rebind NotificationListener: ${e.message}")
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Log.i(TAG, "Notification Listener Created")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.i(TAG, "Notification Listener Destroyed")
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        instance = this
        Log.i(TAG, "Notification Listener Connected")
        pushActiveNotifications()
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        instance = null
        Log.i(TAG, "Notification Listener Disconnected")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        pushActiveNotifications()
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        super.onNotificationRemoved(sbn)
        pushActiveNotifications()
    }

    fun pushActiveNotifications() {
        try {
            val prefs = getSharedPreferences("nexuslink_preferences", android.content.Context.MODE_PRIVATE)
            val isBatterySaver = prefs.getBoolean("battery_saver_enabled", false)
            val isNotifEnabled = prefs.getBoolean("notif_sync_enabled", true)
            if (isBatterySaver || !isNotifEnabled) {
                val payload = JSONObject().apply {
                    put("notifications", JSONArray())
                }
                ConnManagerProxy.sendMessage("sync_notifications", payload)
                return
            }

            val activeNotifs = activeNotifications ?: return
            val array = JSONArray()
            for (sbn in activeNotifs) {
                val n = sbn.notification
                val extras = n.extras
                val title = extras.getCharSequence(android.app.Notification.EXTRA_TITLE)?.toString() ?: ""
                val text = extras.getCharSequence(android.app.Notification.EXTRA_TEXT)?.toString() ?: ""
                val packageName = sbn.packageName

                // Skip system or empty notifications
                if (title.isBlank() && text.isBlank()) continue

                val item = JSONObject().apply {
                    put("id", sbn.key)
                    put("package", packageName)
                    put("title", title)
                    put("text", text)
                    put("post_time", sbn.postTime)
                    put("is_clearable", sbn.isClearable)
                }
                array.put(item)
            }

            val payload = JSONObject().apply {
                put("notifications", array)
            }
            ConnManagerProxy.sendMessage("sync_notifications", payload)
        } catch (e: Exception) {
            Log.e(TAG, "Error pushing notifications: ${e.message}")
        }
    }
}
