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
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flatMapLatest
import com.google.firebase.database.DataSnapshot
import com.google.firebase.database.DatabaseError
import com.google.firebase.database.ChildEventListener
import com.google.firebase.database.FirebaseDatabase
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

    // Already attempted auto-connect fingerprints for this screen lifetime
    private val attemptedAutoConnects = mutableSetOf<String>()

    val connectionState: StateFlow<ConnectionState> = 
        connectionManager.uiState.map { it.connectionState }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ConnectionState.Disconnected)

    private val activePeerFingerprint: StateFlow<String?> =
        connectionManager.uiState.map { it.peerFingerprint }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val trustedPeers = peerStore.peers

    private val cloudRelayTimestamps = MutableStateFlow<Map<String, Long>>(emptyMap())

    private val timeTickFlow = flow {
        while(true) {
            emit(System.currentTimeMillis())
            delay(10_000)
        }
    }

    /** Live list of discovered devices, annotated with pairing status. */
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    val devices: StateFlow<List<NexusDevice>> =
        combine(
            refreshTrigger.flatMapLatest { discoveryManager.discoverDevices() },
            peerStore.peers,
            cloudRelayTimestamps,
            activePeerFingerprint,
            timeTickFlow
        ) { discovered, trustedPeers, timestamps, activeFingerprint, currentTime ->
            _isScanning.value = true
            android.util.Log.d("DiscoveryVM", "combine: discovered=${discovered.size}, trusted=${trustedPeers.size}, timestamps=${timestamps.size}, active=$activeFingerprint")
            trustedPeers.forEach { (fp, peer) ->
                val lastSeen = timestamps[fp] ?: 0L
                android.util.Log.d("DiscoveryVM", "peer fp=$fp, name=${peer.displayName}, lastSeen=$lastSeen, diff=${currentTime - lastSeen}")
            }

            // Clean up attempted auto-connects for devices that are no longer discovered
            val discoveredFingerprints = discovered.mapNotNull { it.fingerprint }.toSet()
            synchronized(attemptedAutoConnects) {
                attemptedAutoConnects.retainAll(discoveredFingerprints)
            }

            val result = discovered.map { device ->
                device.copy(isPaired = device.fingerprint?.let { trustedPeers.containsKey(it) } ?: false)
            }.toMutableList()

            trustedPeers.forEach { (fp, peer) ->
                if (!discoveredFingerprints.contains(fp)) {
                    val lastSeen = timestamps[fp] ?: 0L
                    val isCloudActive = fp == activeFingerprint
                    // Using 10 minutes threshold to tolerate clock drift between PC and phone
                    val isOnline = isCloudActive || (currentTime - lastSeen) < 600_000
                    if (isOnline) {
                        result.add(NexusDevice(
                            name = "Cloud Relay: ${peer.displayName}",
                            host = "cloud",
                            port = 0,
                            fingerprint = fp,
                            isPaired = true
                        ))
                    }
                }
            }
            result.toList()
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
        viewModelScope.launch {
            val dbRef = FirebaseDatabase.getInstance("https://devicelink-d4665-default-rtdb.asia-southeast1.firebasedatabase.app/").reference.child("devices")
            val listener = object : ChildEventListener {
                override fun onChildAdded(snapshot: DataSnapshot, previousChildName: String?) {
                    val fp = snapshot.key ?: return
                    val timestamp = snapshot.child("pc_online").child("timestamp").getValue(Long::class.java) ?: 0L
                    if (timestamp > 0L) {
                        cloudRelayTimestamps.value = cloudRelayTimestamps.value.toMutableMap().apply { put(fp, timestamp) }
                    }
                }

                override fun onChildChanged(snapshot: DataSnapshot, previousChildName: String?) {
                    val fp = snapshot.key ?: return
                    val timestamp = snapshot.child("pc_online").child("timestamp").getValue(Long::class.java) ?: 0L
                    if (timestamp > 0L) {
                        cloudRelayTimestamps.value = cloudRelayTimestamps.value.toMutableMap().apply { put(fp, timestamp) }
                    }
                }

                override fun onChildRemoved(snapshot: DataSnapshot) {
                    val fp = snapshot.key ?: return
                    cloudRelayTimestamps.value = cloudRelayTimestamps.value.toMutableMap().apply { remove(fp) }
                }

                override fun onChildMoved(snapshot: DataSnapshot, previousChildName: String?) {}

                override fun onCancelled(error: DatabaseError) {}
            }

            dbRef.addChildEventListener(listener)
        }
    }
}
