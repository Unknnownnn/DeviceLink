package com.nexuslink.app.services

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothHeadset
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.telecom.TelecomManager
import android.telephony.TelephonyManager
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * Singleton manager for the phone call bridge between the Android device and the PC agent.
 *
 * Responsibilities:
 * - Notifies the PC when an incoming call is ringing on the phone.
 * - Sends call status updates (answered, ended) to the PC.
 * - Handles `make_call` commands from the PC by launching the Android dialer.
 * - Syncs the phone's contacts to the PC on request.
 * - Monitors Bluetooth HFP connection state and exposes it as a [StateFlow].
 */
object CallBridgeManager {

    private const val TAG = "CallBridgeManager"

    // ── Bluetooth HFP State ──────────────────────────────────────────────────
    private val _bluetoothConnected = MutableStateFlow(false)
    val bluetoothConnected: StateFlow<Boolean> = _bluetoothConnected

    private val scope = CoroutineScope(Dispatchers.IO)

    // ── Setter used by BluetoothStateReceiver ────────────────────────────────
    fun setBluetoothConnected(connected: Boolean) {
        _bluetoothConnected.value = connected
        Log.i(TAG, "Bluetooth HFP connected: $connected")
        sendToPc("bt_status", JSONObject().apply { put("connected", connected) })
    }

    /**
     * Check current Bluetooth HFP profile connection state and update the flow.
     * Should be called at app startup and whenever Bluetooth events arrive.
     */
    fun refreshBluetoothState(context: Context) {
        scope.launch {
            try {
                val btManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
                val adapter = btManager?.adapter ?: return@launch
                val connectedDevices = adapter.getProfileConnectionState(BluetoothProfile.HEADSET)
                setBluetoothConnected(connectedDevices == BluetoothAdapter.STATE_CONNECTED)
            } catch (e: SecurityException) {
                Log.w(TAG, "Bluetooth permission not granted: ${e.message}")
                setBluetoothConnected(false)
            } catch (e: Exception) {
                Log.e(TAG, "refreshBluetoothState error: ${e.message}")
                setBluetoothConnected(false)
            }
        }
    }

    // ── Incoming call notification → PC ─────────────────────────────────────

    fun onIncomingCall(context: Context, number: String) {
        val name = resolveContactName(context, number) ?: number
        Log.i(TAG, "Incoming call: $name ($number) → forwarding to PC")
        sendToPc("incoming_call", JSONObject().apply {
            put("number", number)
            put("name", name)
        })
    }

    fun onCallAnswered(context: Context) {
        Log.i(TAG, "Call answered (OFFHOOK)")
        sendToPc("call_status", JSONObject().apply { put("status", "offhook") })
    }

    fun onCallEnded(context: Context) {
        Log.i(TAG, "Call ended (IDLE)")
        sendToPc("call_status", JSONObject().apply { put("status", "idle") })
    }

    // ── Call Control from PC ─────────────────────────────────────────────────

    /**
     * Answers an incoming call. Requires Manifest.permission.ANSWER_PHONE_CALLS on API 26+
     */
    fun answerCall(context: Context) {
        Log.i(TAG, "Answering incoming call from PC...")
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val telecomManager = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
                if (context.checkSelfPermission(android.Manifest.permission.ANSWER_PHONE_CALLS) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    telecomManager.acceptRingingCall()
                    Log.i(TAG, "Accepted call using TelecomManager.acceptRingingCall()")
                } else {
                    Log.w(TAG, "Cannot answer call: ANSWER_PHONE_CALLS permission not granted")
                }
            } else {
                val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
                val method = telephonyManager.javaClass.getDeclaredMethod("getITelephony")
                method.isAccessible = true
                val iTelephony = method.invoke(telephonyManager)
                val answerRingingCallMethod = iTelephony.javaClass.getDeclaredMethod("answerRingingCall")
                answerRingingCallMethod.invoke(iTelephony)
                Log.i(TAG, "Accepted call using TelephonyManager reflection")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to answer call: ${e.message}")
        }
    }

    /**
     * Rejects/declines an incoming call.
     */
    fun declineCall(context: Context) {
        Log.i(TAG, "Declining incoming call from PC...")
        endCall(context)
    }

    /**
     * Hangs up an active call.
     */
    fun hangUpCall(context: Context) {
        Log.i(TAG, "Hanging up active call from PC...")
        endCall(context)
    }

    private fun endCall(context: Context) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val telecomManager = context.getSystemService(Context.TELECOM_SERVICE) as TelecomManager
                val result = telecomManager.endCall()
                Log.i(TAG, "Ended call via TelecomManager.endCall() returned: $result")
            } else {
                val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
                val method = telephonyManager.javaClass.getDeclaredMethod("getITelephony")
                method.isAccessible = true
                val iTelephony = method.invoke(telephonyManager)
                val endCallMethod = iTelephony.javaClass.getDeclaredMethod("endCall")
                endCallMethod.invoke(iTelephony)
                Log.i(TAG, "Ended call via TelephonyManager reflection")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to end/decline call: ${e.message}")
        }
    }

    // ── Outgoing call: PC → Android ──────────────────────────────────────────

    /**
     * Called when the PC sends a `make_call` message. Places the call immediately if
     * permission is granted, otherwise launches the system dialer with number pre-filled.
     */
    fun onMakeCall(context: Context, number: String) {
        Log.i(TAG, "PC requested call to: $number")
        try {
            if (context.checkSelfPermission(android.Manifest.permission.CALL_PHONE) == android.content.pm.PackageManager.PERMISSION_GRANTED) {
                val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:${Uri.encode(number)}")).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
                Log.i(TAG, "Placed direct call via ACTION_CALL to: $number")
            } else {
                Log.w(TAG, "CALL_PHONE permission not granted, falling back to ACTION_DIAL")
                val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(number)}")).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to place call: ${e.message}")
        }
    }

    // ── Contact sync: Android → PC ───────────────────────────────────────────

    fun syncContactsToPC(context: Context) {
        scope.launch {
            val contacts = fetchContacts(context)
            val arr = JSONArray()
            contacts.forEach { (name, number) ->
                arr.put(JSONObject().apply {
                    put("name", name)
                    put("number", number)
                })
            }
            sendToPc("sync_contacts", JSONObject().apply { put("contacts", arr) })
            Log.i(TAG, "Synced ${contacts.size} contacts to PC")
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private fun resolveContactName(context: Context, number: String): String? {
        if (number.isBlank()) return null
        return try {
            val uri = Uri.withAppendedPath(
                ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
                Uri.encode(number)
            )
            context.contentResolver.query(
                uri,
                arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
                null, null, null
            )?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0) else null
            }
        } catch (e: Exception) {
            Log.w(TAG, "resolveContactName failed: ${e.message}")
            null
        }
    }

    private fun fetchContacts(context: Context): List<Pair<String, String>> {
        val results = mutableListOf<Pair<String, String>>()
        return try {
            context.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                    ContactsContract.CommonDataKinds.Phone.NUMBER
                ),
                null, null,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " ASC"
            )?.use { cursor ->
                val nameIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                val seen = mutableSetOf<String>()
                while (cursor.moveToNext()) {
                    val name = cursor.getString(nameIdx) ?: continue
                    val num = cursor.getString(numIdx) ?: continue
                    val key = "$name|$num"
                    if (seen.add(key)) results.add(Pair(name, num))
                }
            }
            results
        } catch (e: Exception) {
            Log.e(TAG, "fetchContacts error: ${e.message}")
            results
        }
    }

    private fun sendToPc(type: String, payload: JSONObject) {
        // Reach the singleton ConnectionManager via Hilt's injected application context proxy
        ConnManagerProxy.sendMessage(type, payload)
    }
}
