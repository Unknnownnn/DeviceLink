package com.nexuslink.app.services

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHeadset
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Listens for Bluetooth adapter state changes and HFP headset profile
 * connection/disconnection events.
 *
 * Updates both [CallBridgeManager] (for the simple boolean flag used across the
 * app) and [BluetoothHFPManager] (for the per-device list in the BT panel).
 *
 * Registered dynamically in [NexusForegroundService] so it respects runtime
 * permission grants.
 */
class BluetoothStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        try {
            when (intent.action) {
                BluetoothAdapter.ACTION_STATE_CHANGED -> {
                    val state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR)
                    when (state) {
                        BluetoothAdapter.STATE_OFF -> {
                            CallBridgeManager.setBluetoothConnected(false)
                            BluetoothHFPManager.refreshDeviceList()
                        }
                        BluetoothAdapter.STATE_ON -> {
                            BluetoothHFPManager.init(context)
                            CallBridgeManager.refreshBluetoothState(context)
                        }
                    }
                    Log.i(TAG, "Bluetooth adapter state → $state")
                }

                BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED -> {
                    @Suppress("DEPRECATION")
                    val device: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    val newState = intent.getIntExtra(BluetoothHeadset.EXTRA_STATE, -1)
                    val connected = newState == BluetoothHeadset.STATE_CONNECTED

                    Log.i(TAG, "HFP state → ${device?.address} connected=$connected (state=$newState)")

                    // Update per-device list
                    BluetoothHFPManager.onHFPStateChanged(device, newState)

                    // Update simple global flag
                    CallBridgeManager.setBluetoothConnected(connected)
                }

                BluetoothDevice.ACTION_ACL_CONNECTED -> {
                    @Suppress("DEPRECATION")
                    val device: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    Log.i(TAG, "ACL connected: ${device?.address}")
                    // Refresh after a short delay to let HFP state settle
                    BluetoothHFPManager.refreshDeviceList()
                }

                BluetoothDevice.ACTION_ACL_DISCONNECTED -> {
                    @Suppress("DEPRECATION")
                    val device: BluetoothDevice? = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    Log.i(TAG, "ACL disconnected: ${device?.address}")
                    BluetoothHFPManager.onHFPStateChanged(device, BluetoothProfile.STATE_DISCONNECTED)
                }
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Error in onReceive: ${e.message}", e)
        }
    }

    companion object {
        private const val TAG = "BluetoothStateReceiver"
    }
}
