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

    private val _batterySaverEnabled = MutableStateFlow(prefs.getBoolean("battery_saver_enabled", false))
    val batterySaverEnabled: StateFlow<Boolean> = _batterySaverEnabled

    private val _bgLaunchEnabled = MutableStateFlow(prefs.getBoolean("bg_launch_enabled", true))
    val bgLaunchEnabled: StateFlow<Boolean> = _bgLaunchEnabled

    private val _notifSyncEnabled = MutableStateFlow(prefs.getBoolean("notif_sync_enabled", true))
    val notifSyncEnabled: StateFlow<Boolean> = _notifSyncEnabled

    private val _phoneSyncEnabled = MutableStateFlow(prefs.getBoolean("phone_sync_enabled", true))
    val phoneSyncEnabled: StateFlow<Boolean> = _phoneSyncEnabled

    private val _clipImageSyncEnabled = MutableStateFlow(prefs.getBoolean("clip_image_sync_enabled", true))
    val clipImageSyncEnabled: StateFlow<Boolean> = _clipImageSyncEnabled

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

    fun setBatterySaverEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("battery_saver_enabled", enabled).apply()
        _batterySaverEnabled.value = enabled
    }

    fun setBgLaunchEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("bg_launch_enabled", enabled).apply()
        _bgLaunchEnabled.value = enabled
    }

    fun setNotifSyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("notif_sync_enabled", enabled).apply()
        _notifSyncEnabled.value = enabled
    }

    fun setPhoneSyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("phone_sync_enabled", enabled).apply()
        _phoneSyncEnabled.value = enabled
    }

    fun setClipImageSyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("clip_image_sync_enabled", enabled).apply()
        _clipImageSyncEnabled.value = enabled
    }

    fun isBgLaunchActive(): Boolean {
        return !_batterySaverEnabled.value && _bgLaunchEnabled.value
    }

    fun isNotifSyncActive(): Boolean {
        return !_batterySaverEnabled.value && _notifSyncEnabled.value
    }

    fun isPhoneSyncActive(): Boolean {
        return !_batterySaverEnabled.value && _phoneSyncEnabled.value
    }

    fun isClipImageSyncActive(): Boolean {
        return !_batterySaverEnabled.value && _clipImageSyncEnabled.value
    }
}
