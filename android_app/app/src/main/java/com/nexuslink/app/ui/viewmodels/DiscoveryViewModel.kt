package com.nexuslink.app.ui.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.firebase.database.ChildEventListener
import com.google.firebase.database.DataSnapshot
import com.google.firebase.database.DatabaseError
import com.google.firebase.database.FirebaseDatabase
import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.data.PeerStore
import com.nexuslink.app.data.PreferencesManager
import com.nexuslink.app.data.TrustedPeer
import com.nexuslink.app.network.ConnectionManager
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.network.NsdDiscoveryManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

private const val CLOUD_PRESENCE_TIMEOUT_MS = 600_000L

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

    private val refreshTrigger = MutableStateFlow(0)
    
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            refreshTrigger.value += 1
            delay(1500)
            _isRefreshing.value = false
        }
    }

    val connectionState: StateFlow<ConnectionState> = 
        connectionManager.uiState.map { it.connectionState }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ConnectionState.Disconnected)

    val activeFingerprint: StateFlow<String?> =
        connectionManager.uiState.map { 
            if (it.connectionState is ConnectionState.Connected) it.peerFingerprint else null 
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val trustedPeers = peerStore.peers

    private val cloudRelayTimestamps = callbackFlow {
        var timestamps = emptyMap<String, Long>()
        trySend(timestamps)

        val dbRef = try {
            FirebaseDatabase.getInstance("https://devicelink-d4665-default-rtdb.asia-southeast1.firebasedatabase.app/")
                .reference.child("devices")
        } catch (e: IllegalStateException) {
            android.util.Log.w("DiscoveryVM", "Firebase presence is unavailable", e)
            close()
            return@callbackFlow
        }

        val listener = object : ChildEventListener {
            override fun onChildAdded(snapshot: DataSnapshot, previousChildName: String?) {
                onChildChanged(snapshot, previousChildName)
            }

            override fun onChildChanged(snapshot: DataSnapshot, previousChildName: String?) {
                val fp = snapshot.key ?: return
                val timestamp = snapshot.child("pc_online").child("timestamp").getValue(Long::class.java)
                timestamps = if (timestamp != null) timestamps + (fp to timestamp) else timestamps - fp
                trySend(timestamps)
            }

            override fun onChildRemoved(snapshot: DataSnapshot) {
                val fp = snapshot.key ?: return
                timestamps = timestamps - fp
                trySend(timestamps)
            }

            override fun onChildMoved(snapshot: DataSnapshot, previousChildName: String?) {}

            override fun onCancelled(error: DatabaseError) {
                trySend(emptyMap())
                close()
            }
        }
        dbRef.addChildEventListener(listener)
        awaitClose { dbRef.removeEventListener(listener) }
    }

    private val timeTickFlow = flow {
        while(true) {
            emit(System.currentTimeMillis())
            delay(10_000)
        }
    }

    /** Saved PCs remain selectable even when discovery has no result for them. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val devices: StateFlow<List<NexusDevice>> =
        combine(
            refreshTrigger.flatMapLatest { discoveryManager.discoverDevices() },
            peerStore.peers,
            cloudRelayTimestamps,
            timeTickFlow
        ) { discovered, trustedPeers, timestamps, currentTime ->
            buildDeviceList(discovered, trustedPeers, timestamps, currentTime)
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = buildDeviceList(emptyList(), trustedPeers.value, emptyMap(), 0L),
        )

    companion object {
        var hasAttemptedConnectionThisSession = false
    }
}

internal fun buildDeviceList(
    discovered: List<NexusDevice>,
    trustedPeers: Map<String, TrustedPeer>,
    cloudTimestamps: Map<String, Long>,
    currentTime: Long,
): List<NexusDevice> {
    val localFingerprints = discovered.mapNotNull { it.fingerprint }.toSet()
    val localDevices = discovered.map { device ->
        device.copy(isPaired = device.fingerprint in trustedPeers)
    }
    val savedDevices = trustedPeers.values.filterNot { it.fingerprint in localFingerprints }.map { peer ->
        val lastSeen = cloudTimestamps[peer.fingerprint]
        val reachable = lastSeen != null &&
            currentTime - lastSeen in -CLOUD_PRESENCE_TIMEOUT_MS..CLOUD_PRESENCE_TIMEOUT_MS
        NexusDevice(
            name = peer.displayName,
            host = "cloud",
            port = 0,
            fingerprint = peer.fingerprint,
            isPaired = true,
            isReachable = reachable,
        )
    }
    return localDevices + savedDevices
}
