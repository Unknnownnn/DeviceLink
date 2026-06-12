package com.nexuslink.app.ui.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.PreferencesManager
import com.nexuslink.app.network.ConnectionManager
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.network.NsdDiscoveryManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * ViewModel for the device discovery screen.
 *
 * Combines real-time mDNS discovery results with the local trusted peers store
 * to annotate each [NexusDevice] with its pairing state.
 */
@HiltViewModel
class DiscoveryViewModel @Inject constructor(
    private val discoveryManager: NsdDiscoveryManager,
    private val peerStore: PeerStore,
    private val connectionManager: ConnectionManager,
    val preferencesManager: PreferencesManager,
) : ViewModel() {

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning

    // Already attempted auto-connect fingerprints for this screen lifetime
    private val attemptedAutoConnects = mutableSetOf<String>()

    val connectionState: StateFlow<ConnectionState> = 
        connectionManager.uiState.map { it.connectionState }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ConnectionState.Disconnected)

    val trustedPeers = peerStore.peers

    /** Live list of discovered devices, annotated with pairing status. */
    val devices: StateFlow<List<NexusDevice>> =
        combine(
            discoveryManager.discoverDevices(),
            peerStore.peers,
        ) { discovered, trustedPeers ->
            _isScanning.value = true

            // Clean up attempted auto-connects for devices that are no longer discovered
            val discoveredFingerprints = discovered.mapNotNull { it.fingerprint }.toSet()
            synchronized(attemptedAutoConnects) {
                attemptedAutoConnects.retainAll(discoveredFingerprints)
            }

            discovered.map { device ->
                device.copy(isPaired = device.fingerprint?.let { trustedPeers.containsKey(it) } ?: false)
            }
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = emptyList(),
        )

    fun hasAttemptedAutoConnect(fingerprint: String): Boolean {
        return synchronized(attemptedAutoConnects) {
            attemptedAutoConnects.contains(fingerprint)
        }
    }

    fun markAutoConnectAttempted(fingerprint: String) {
        synchronized(attemptedAutoConnects) {
            attemptedAutoConnects.add(fingerprint)
        }
    }

    companion object {
        var hasAutoConnectedThisSession = false
    }

    init {
        // Kick off discovery when ViewModel is created
        viewModelScope.launch { /* Flow starts lazily on first subscriber */ }
    }
}
