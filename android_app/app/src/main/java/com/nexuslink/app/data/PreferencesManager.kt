package com.nexuslink.app.data

import android.content.Context
import android.content.SharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class PreferencesManager @Inject constructor(
    @ApplicationContext context: Context
) {
    private val prefs: SharedPreferences = context.getSharedPreferences("nexuslink_preferences", Context.MODE_PRIVATE)

    private val _autoConnectEnabled = MutableStateFlow(prefs.getBoolean("auto_connect_enabled", true))
    val autoConnectEnabled: StateFlow<Boolean> = _autoConnectEnabled

    private val _preferredAutoConnectFingerprint = MutableStateFlow(prefs.getString("preferred_auto_connect_fingerprint", null))
    val preferredAutoConnectFingerprint: StateFlow<String?> = _preferredAutoConnectFingerprint

    fun setAutoConnectEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("auto_connect_enabled", enabled).apply()
        _autoConnectEnabled.value = enabled
    }

    fun setPreferredAutoConnectFingerprint(fingerprint: String?) {
        prefs.edit().putString("preferred_auto_connect_fingerprint", fingerprint).apply()
        _preferredAutoConnectFingerprint.value = fingerprint
    }
}
