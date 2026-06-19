package com.nexuslink.app.ui.viewmodels

import androidx.lifecycle.ViewModel
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.PreferencesManager
import com.nexuslink.app.data.TrustedPeer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val peerStore: PeerStore,
    private val preferencesManager: PreferencesManager,
) : ViewModel() {

    val trustedPeers: StateFlow<Map<String, TrustedPeer>> = peerStore.peers
    val autoConnectEnabled: StateFlow<Boolean> = preferencesManager.autoConnectEnabled
    val preferredAutoConnectFingerprint: StateFlow<String?> = preferencesManager.preferredAutoConnectFingerprint

    val batterySaverEnabled: StateFlow<Boolean> = preferencesManager.batterySaverEnabled
    val bgLaunchEnabled: StateFlow<Boolean> = preferencesManager.bgLaunchEnabled
    val notifSyncEnabled: StateFlow<Boolean> = preferencesManager.notifSyncEnabled
    val phoneSyncEnabled: StateFlow<Boolean> = preferencesManager.phoneSyncEnabled
    val clipImageSyncEnabled: StateFlow<Boolean> = preferencesManager.clipImageSyncEnabled

    fun setAutoConnectEnabled(enabled: Boolean) {
        preferencesManager.setAutoConnectEnabled(enabled)
    }

    fun setPreferredAutoConnectFingerprint(fingerprint: String?) {
        preferencesManager.setPreferredAutoConnectFingerprint(fingerprint)
    }

    fun setBatterySaverEnabled(enabled: Boolean) {
        preferencesManager.setBatterySaverEnabled(enabled)
    }

    fun setBgLaunchEnabled(enabled: Boolean) {
        preferencesManager.setBgLaunchEnabled(enabled)
    }

    fun setNotifSyncEnabled(enabled: Boolean) {
        preferencesManager.setNotifSyncEnabled(enabled)
    }

    fun setPhoneSyncEnabled(enabled: Boolean) {
        preferencesManager.setPhoneSyncEnabled(enabled)
    }

    fun setClipImageSyncEnabled(enabled: Boolean) {
        preferencesManager.setClipImageSyncEnabled(enabled)
    }

    fun removeTrustedPeer(fingerprint: String) {
        peerStore.removePeer(fingerprint)
        if (preferredAutoConnectFingerprint.value == fingerprint) {
            setPreferredAutoConnectFingerprint(null)
        }
    }
}
