package com.nexuslink.app.services

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.util.Log

/**
 * BroadcastReceiver that listens for phone call state changes (RINGING, OFFHOOK, IDLE).
 *
 * When a call is RINGING, it fires the incoming call notification to the PC via
 * [CallBridgeManager]. When the call ends (IDLE) or is answered (OFFHOOK),
 * it sends the corresponding status update to the PC.
 */
class PhoneCallReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return

        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER) ?: ""

        Log.i(TAG, "Phone state: $state  number: $number")

        when (state) {
            TelephonyManager.EXTRA_STATE_RINGING -> {
                CallBridgeManager.onIncomingCall(context, number)
            }
            TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                CallBridgeManager.onCallAnswered(context)
            }
            TelephonyManager.EXTRA_STATE_IDLE -> {
                CallBridgeManager.onCallEnded(context)
            }
        }
    }

    companion object {
        private const val TAG = "PhoneCallReceiver"
    }
}
