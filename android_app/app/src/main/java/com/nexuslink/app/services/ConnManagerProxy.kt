package com.nexuslink.app.services

import com.nexuslink.app.network.ConnectionManager
import org.json.JSONObject

/**
 * Application-level bridge so that non-Hilt singletons (like [CallBridgeManager]) can
 * dispatch WebSocket messages through the Hilt-managed [ConnectionManager].
 *
 * The [ConnectionManager] calls [register] during its own initialisation (via Hilt inject).
 */
object ConnManagerProxy {
    @Volatile
    private var manager: ConnectionManager? = null

    fun register(cm: ConnectionManager) {
        manager = cm
    }

    fun sendMessage(type: String, payload: JSONObject) {
        manager?.sendMessage(type, payload)
    }
}
