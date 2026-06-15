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

    companion object {
        private const val UPDATE_PROMPT_SNOOZE_UNTIL_MS = "update_prompt_snooze_until_ms"
        private const val UPDATE_PROMPT_SNOOZE_DURATION_MS = 12L * 60L * 60L * 1000L
    }

    private val _autoConnectEnabled = MutableStateFlow(prefs.getBoolean("auto_connect_enabled", true))
    val autoConnectEnabled: StateFlow<Boolean> = _autoConnectEnabled

    private val _preferredAutoConnectFingerprint = MutableStateFlow(prefs.getString("preferred_auto_connect_fingerprint", null))
    val preferredAutoConnectFingerprint: StateFlow<String?> = _preferredAutoConnectFingerprint

    private val _updatePromptSnoozeUntilMs = MutableStateFlow(prefs.getLong(UPDATE_PROMPT_SNOOZE_UNTIL_MS, 0L))
    val updatePromptSnoozeUntilMs: StateFlow<Long> = _updatePromptSnoozeUntilMs

    fun setAutoConnectEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("auto_connect_enabled", enabled).apply()
        _autoConnectEnabled.value = enabled
    }

    fun setPreferredAutoConnectFingerprint(fingerprint: String?) {
        prefs.edit().putString("preferred_auto_connect_fingerprint", fingerprint).apply()
        _preferredAutoConnectFingerprint.value = fingerprint
    }

    fun snoozeUpdatePrompt(durationMs: Long = UPDATE_PROMPT_SNOOZE_DURATION_MS) {
        val snoozeUntil = System.currentTimeMillis() + durationMs
        prefs.edit().putLong(UPDATE_PROMPT_SNOOZE_UNTIL_MS, snoozeUntil).apply()
        _updatePromptSnoozeUntilMs.value = snoozeUntil
    }

    fun isUpdatePromptSnoozed(nowMs: Long = System.currentTimeMillis()): Boolean {
        return nowMs < _updatePromptSnoozeUntilMs.value
    }
}
