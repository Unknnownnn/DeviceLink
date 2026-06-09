package com.nexuslink.app.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import com.nexuslink.app.data.NexusDevice
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "NsdDiscoveryManager"
private const val SERVICE_TYPE = "_devicelink._tcp"

/**
 * Wraps Android's [NsdManager] to expose discovered NexusLink services as a
 * Kotlin [Flow] of [NexusDevice] lists.
 *
 * Usage:
 * ```kotlin
 * discoveryManager.discoverDevices().collect { devices ->
 *     // Update UI with discovered devices list
 * }
 * ```
 */
@Singleton
class NsdDiscoveryManager @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val nsdManager: NsdManager =
        context.getSystemService(Context.NSD_SERVICE) as NsdManager

    /**
     * Returns a cold [Flow] that starts mDNS discovery when collected and stops
     * it when the collector is cancelled.  Emits a new list on every discovery
     * or loss event.
     */
    fun discoverDevices(): Flow<List<NexusDevice>> = callbackFlow {
        val discoveredServices = mutableMapOf<String, NexusDevice>()

        // ── Resolve listener factory ─────────────────────────────────────
        fun resolveService(info: NsdServiceInfo) {
            nsdManager.resolveService(info, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    Log.w(TAG, "Resolve failed for ${serviceInfo.serviceName}: $errorCode")
                }

                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    val host = serviceInfo.host?.hostAddress ?: return
                    val port = serviceInfo.port
                    val fp = serviceInfo.attributes[b("fp")]?.toString(Charsets.UTF_8) ?: ""

                    val device = NexusDevice(
                        name = serviceInfo.serviceName,
                        host = host,
                        port = port,
                        fingerprint = fp.ifBlank { null },
                    )
                    discoveredServices[serviceInfo.serviceName] = device
                    Log.i(TAG, "Resolved: ${device.displayName} @ $host:$port")
                    trySend(discoveredServices.values.toList())
                }
            })
        }

        // ── Discovery listener ────────────────────────────────────────────
        val discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "Discovery start failed: $errorCode")
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "Discovery stop failed: $errorCode")
            }

            override fun onDiscoveryStarted(serviceType: String) {
                Log.i(TAG, "mDNS discovery started for $serviceType")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.i(TAG, "mDNS discovery stopped.")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                Log.i(TAG, "Service found: ${serviceInfo.serviceName}")
                resolveService(serviceInfo)
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.i(TAG, "Service lost: ${serviceInfo.serviceName}")
                discoveredServices.remove(serviceInfo.serviceName)
                trySend(discoveredServices.values.toList())
            }
        }

        nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener)

        // Emit initial empty list immediately
        trySend(emptyList())

        awaitClose {
            try {
                nsdManager.stopServiceDiscovery(discoveryListener)
            } catch (e: Exception) {
                Log.w(TAG, "Error stopping discovery: ${e.message}")
            }
        }
    }

    private fun b(s: String): String = s  // helper for attribute key clarity
}
