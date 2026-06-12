package com.nexuslink.app.services

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHeadset
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Manages Bluetooth HFP (Hands-Free Profile) connections for phone call bridging.
 *
 * Key design decisions:
 * - Uses the BluetoothHeadset profile proxy (phone acts as Audio Gateway / AG role).
 * - Scans paired devices and shows which ones have HFP capability.
 * - Exposes per-device connection states as a StateFlow for the UI.
 * - Can programmatically connect/disconnect HFP to a specific paired device.
 *
 * Windows-side note: Windows HFP only "stays connected" during active calls by default.
 * This is normal Windows behavior — the profile connects/disconnects as needed.
 * The indicator in the app UI shows the live HFP state, which will flicker unless
 * an active call is in progress.
 */
object BluetoothHFPManager {

    private const val TAG = "BluetoothHFPManager"

    data class BTDevice(
        val name: String,
        val address: String,
        val bondState: Int,            // BluetoothDevice.BOND_BONDED = 12
        val hfpState: Int = BluetoothProfile.STATE_DISCONNECTED,
        val supportsHFP: Boolean = false,
    ) {
        val isConnected get() = hfpState == BluetoothProfile.STATE_CONNECTED
        val isConnecting get() = hfpState == BluetoothProfile.STATE_CONNECTING
    }

    private val _devices = MutableStateFlow<List<BTDevice>>(emptyList())
    val devices: StateFlow<List<BTDevice>> = _devices

    private val _statusMessage = MutableStateFlow("")
    val statusMessage: StateFlow<String> = _statusMessage

    private var headsetProxy: BluetoothHeadset? = null
    private var adapter: BluetoothAdapter? = null
    private val scope = CoroutineScope(Dispatchers.IO)

    /** Called once at app start (or when BT permission is granted). */
    fun init(context: Context) {
        scope.launch {
            try {
                val btManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
                adapter = btManager?.adapter
                if (adapter == null) {
                    _statusMessage.value = "Bluetooth not available on this device"
                    return@launch
                }
                if (!adapter!!.isEnabled) {
                    _statusMessage.value = "Bluetooth is turned off"
                    return@launch
                }
                openHeadsetProxy(context)
            } catch (e: Throwable) {
                Log.e(TAG, "init error: ${e.message}", e)
                _statusMessage.value = "Bluetooth access error"
            }
        }
    }

    /**
     * Open the HFP profile proxy. Once opened, we can call connect/disconnect
     * on individual paired devices.
     */
    private fun openHeadsetProxy(context: Context) {
        try {
            adapter?.getProfileProxy(context, object : BluetoothProfile.ServiceListener {
                override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                    try {
                        if (profile == BluetoothProfile.HEADSET) {
                            headsetProxy = proxy as? BluetoothHeadset
                            Log.i(TAG, "HFP proxy opened")
                            refreshDeviceList()
                        }
                    } catch (e: Throwable) {
                        Log.e(TAG, "onServiceConnected error: ${e.message}", e)
                    }
                }
                override fun onServiceDisconnected(profile: Int) {
                    headsetProxy = null
                    Log.w(TAG, "HFP proxy disconnected")
                }
            }, BluetoothProfile.HEADSET)
        } catch (e: Throwable) {
            Log.e(TAG, "getProfileProxy error: ${e.message}", e)
        }
    }

    /** Refresh the list of paired devices and their HFP connection states. */
    fun refreshDeviceList() {
        scope.launch {
            try {
                val adpt = adapter ?: return@launch
                if (!adpt.isEnabled) {
                    _statusMessage.value = "Bluetooth is off"
                    _devices.value = emptyList()
                    return@launch
                }

                val pairedDevices: Set<BluetoothDevice> = try {
                    adpt.bondedDevices ?: emptySet()
                } catch (e: Throwable) {
                    Log.w(TAG, "Failed to get bonded devices: ${e.message}")
                    emptySet()
                }
                val proxy = headsetProxy

                // Get currently HFP-connected devices
                val connectedAddresses: Set<String> = try {
                    proxy?.connectedDevices?.map { it.address }?.toSet() ?: emptySet()
                } catch (e: Throwable) {
                    Log.w(TAG, "Failed to get connected devices: ${e.message}")
                    emptySet()
                }

                val list = pairedDevices.map { device ->
                    val name = try { device.name ?: device.address } catch (_: Throwable) { device.address }
                    val hfpState = if (proxy != null) {
                        try { proxy.getConnectionState(device) } catch (_: Throwable) { BluetoothProfile.STATE_DISCONNECTED }
                    } else {
                        BluetoothProfile.STATE_DISCONNECTED
                    }
                    // Check if device supports HFP (device class: phone or headset)
                    val uuids = try { device.uuids } catch (_: Throwable) { null }
                    val supportsHFP = uuids?.any { uuid ->
                        val str = uuid.uuid.toString().lowercase()
                        str.startsWith("0000111e") || // HFP HF
                        str.startsWith("00001108") || // Headset
                        str.startsWith("0000111f")    // HFP AG
                    } ?: true // assume true if we can't check

                    BTDevice(
                        name = name,
                        address = device.address,
                        bondState = try { device.bondState } catch (_: Throwable) { BluetoothDevice.BOND_NONE },
                        hfpState = hfpState,
                        supportsHFP = supportsHFP,
                    )
                }.sortedWith(compareByDescending<BTDevice> { it.isConnected }.thenBy { it.name })

                _devices.value = list
                _statusMessage.value = if (list.isEmpty()) "No paired Bluetooth devices found" else ""
                Log.i(TAG, "Device list refreshed: ${list.size} paired devices")
            } catch (e: Throwable) {
                _statusMessage.value = "Bluetooth access error"
                Log.e(TAG, "refreshDeviceList error: ${e.message}", e)
            }
        }
    }

    /**
     * Connect HFP to the given device address.
     * Works by calling the hidden BluetoothHeadset.connect() via the proxy.
     */
    fun connectDevice(address: String, context: Context) {
        scope.launch {
            val proxy = headsetProxy
            if (proxy == null) {
                _statusMessage.value = "HFP service not ready. Tap Refresh."
                openHeadsetProxy(context)
                return@launch
            }
            try {
                val adpt = adapter ?: return@launch
                val device = adpt.getRemoteDevice(address)
                // Optimistically update state
                updateDeviceState(address, BluetoothProfile.STATE_CONNECTING)
                _statusMessage.value = "Connecting to ${device.name ?: address}..."

                // BluetoothHeadset.connect() is @hide but accessible via reflection
                val connected = try {
                    val method = proxy.javaClass.getMethod("connect", BluetoothDevice::class.java)
                    method.invoke(proxy, device) as? Boolean ?: false
                } catch (e: Exception) {
                    Log.w(TAG, "connect() reflection failed, trying setPriority workaround: ${e.message}")
                    // Fallback: set priority to ON so Android auto-connects HFP
                    val priMethod = proxy.javaClass.getMethod("setPriority", BluetoothDevice::class.java, Int::class.java)
                    priMethod.invoke(proxy, device, 100)
                    false
                }
                Log.i(TAG, "HFP connect($address) returned $connected")
                // Refresh list after short delay
                kotlinx.coroutines.delay(2000)
                refreshDeviceList()
            } catch (e: SecurityException) {
                _statusMessage.value = "Permission denied for Bluetooth connect"
                Log.w(TAG, "connectDevice: ${e.message}")
            } catch (e: Exception) {
                _statusMessage.value = "Connect failed: ${e.message}"
                Log.e(TAG, "connectDevice error: ${e.message}")
            }
        }
    }

    /** Disconnect HFP from a specific device. */
    fun disconnectDevice(address: String) {
        scope.launch {
            val proxy = headsetProxy ?: return@launch
            try {
                val device = adapter?.getRemoteDevice(address) ?: return@launch
                updateDeviceState(address, BluetoothProfile.STATE_DISCONNECTING)
                val method = proxy.javaClass.getMethod("disconnect", BluetoothDevice::class.java)
                method.invoke(proxy, device)
                kotlinx.coroutines.delay(1500)
                refreshDeviceList()
            } catch (e: Exception) {
                Log.e(TAG, "disconnectDevice error: ${e.message}")
            }
        }
    }

    /** Called by BluetoothStateReceiver when HFP state changes for any device. */
    fun onHFPStateChanged(device: BluetoothDevice?, newState: Int) {
        val address = try { device?.address } catch (_: SecurityException) { null } ?: return
        updateDeviceState(address, newState)

        // Also update the global "any device connected" flag used by CallBridgeManager
        val anyConnected = _devices.value.any { it.isConnected } ||
            newState == BluetoothProfile.STATE_CONNECTED
        CallBridgeManager.setBluetoothConnected(anyConnected)
    }

    private fun updateDeviceState(address: String, newHfpState: Int) {
        _devices.update { list ->
            list.map { if (it.address == address) it.copy(hfpState = newHfpState) else it }
        }
    }

    fun release() {
        adapter?.closeProfileProxy(BluetoothProfile.HEADSET, headsetProxy)
        headsetProxy = null
    }
}
