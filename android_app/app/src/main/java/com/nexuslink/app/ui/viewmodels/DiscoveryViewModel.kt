package com.nexuslink.app.ui.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.network.NsdDiscoveryManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
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
) : ViewModel() {

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning

    /** Live list of discovered devices, annotated with pairing status. */
    val devices: StateFlow<List<NexusDevice>> =
        combine(
            discoveryManager.discoverDevices(),
            peerStore.peers,
        ) { discovered, trustedPeers ->
            _isScanning.value = true
            discovered.map { device ->
                device.copy(isPaired = device.fingerprint?.let { trustedPeers.containsKey(it) } ?: false)
            }
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = emptyList(),
        )

    init {
        // Kick off discovery when ViewModel is created
        viewModelScope.launch { /* Flow starts lazily on first subscriber */ }
    }
}
