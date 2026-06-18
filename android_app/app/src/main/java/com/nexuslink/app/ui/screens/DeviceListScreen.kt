package com.nexuslink.app.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.ui.theme.*
import com.nexuslink.app.ui.viewmodels.DiscoveryViewModel
import com.nexuslink.app.updater.GitHubUpdater
import com.nexuslink.app.updater.UpdaterState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Device Discovery Screen.
 *
 * Shows all NexusLink-capable PCs found on the local network via mDNS.
 * Tapping a device navigates to the QR scanner for pairing.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceListScreen(
    onDeviceSelected: (host: String, port: Int, isPaired: Boolean, fingerprint: String?) -> Unit,
    onManualScan: () -> Unit,
    onSettingsClicked: () -> Unit,
    viewModel: DiscoveryViewModel = hiltViewModel(),
) {
    val devices by viewModel.devices.collectAsState()
    val connectionState by viewModel.connectionState.collectAsState()
    val autoConnectEnabled by viewModel.preferencesManager.autoConnectEnabled.collectAsState()
    val preferredFp by viewModel.preferencesManager.preferredAutoConnectFingerprint.collectAsState()
    val trustedPeers by viewModel.trustedPeers.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()

    val context = LocalContext.current
    val updater = remember { GitHubUpdater(context) }
    val updaterState by updater.state.collectAsState()
    val scope = rememberCoroutineScope()
    val lifecycleOwner = LocalLifecycleOwner.current
    val updatePromptSnoozeUntilMs by viewModel.preferencesManager.updatePromptSnoozeUntilMs.collectAsState()

    var showUpdatePopup by remember { mutableStateOf(false) }
    var updateCheckInFlight by remember { mutableStateOf(false) }

    fun requestUpdateCheck() {
        val now = System.currentTimeMillis()
        if (updateCheckInFlight || viewModel.preferencesManager.isUpdatePromptSnoozed(now)) {
            return
        }

        updateCheckInFlight = true
        updater.resetState()
        scope.launch {
            try {
                updater.checkForUpdates(force = true)
            } finally {
                updateCheckInFlight = false
            }
        }
    }

    LaunchedEffect(Unit) {
        requestUpdateCheck()
    }

    DisposableEffect(lifecycleOwner, updatePromptSnoozeUntilMs) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) {
                requestUpdateCheck()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    // Auto-connect to a verified device if found
    LaunchedEffect(devices, connectionState, autoConnectEnabled, preferredFp, trustedPeers) {
        if (autoConnectEnabled && 
            connectionState is ConnectionState.Disconnected && 
            trustedPeers.isNotEmpty() &&
            !DiscoveryViewModel.hasAutoConnectedThisSession
        ) {
            val targetFp = if (trustedPeers.size == 1) {
                trustedPeers.keys.first()
            } else {
                preferredFp
            }

            if (targetFp != null) {
                val matchingDevice = devices.find { it.fingerprint == targetFp && it.host != "cloud" }
                if (matchingDevice != null && matchingDevice.fingerprint != null) {
                    val fp = matchingDevice.fingerprint
                    DiscoveryViewModel.hasAutoConnectedThisSession = true
                    viewModel.markAutoConnectAttempted(fp)
                    onDeviceSelected(matchingDevice.host, matchingDevice.port, true, fp)
                }
            }
        }
    }

    val currentUpdaterState = updaterState
    LaunchedEffect(currentUpdaterState) {
        if (currentUpdaterState is UpdaterState.UpdateAvailable && !viewModel.preferencesManager.isUpdatePromptSnoozed()) {
            showUpdatePopup = true
        }
    }

    if (showUpdatePopup && currentUpdaterState is UpdaterState.UpdateAvailable) {
        AlertDialog(
            onDismissRequest = { 
                showUpdatePopup = false
                viewModel.preferencesManager.snoozeUpdatePrompt()
            },
            title = {
                Text(
                    text = "Update Available",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
            },
            text = {
                Text(
                    text = "A new version (${currentUpdaterState.latestVersion}) of DeviceLink is available. Would you like to update now?",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showUpdatePopup = false
                        scope.launch {
                            updater.downloadAndInstall(currentUpdaterState.downloadUrl)
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Blue400)
                ) {
                    Text("Update", color = Color.White)
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { 
                        showUpdatePopup = false
                        viewModel.preferencesManager.snoozeUpdatePrompt()
                    }
                ) {
                    Text("Later", color = OnSurfaceDim)
                }
            },
            containerColor = Surface800,
            shape = RoundedCornerShape(16.dp)
        )
    }

    // Modal progress overlay while the update download is active
    if (currentUpdaterState is UpdaterState.Downloading) {
        AlertDialog(
            onDismissRequest = {}, // Force non-dismissible
            title = {
                Text(
                    text = "Downloading Update...",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
            },
            text = {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    LinearProgressIndicator(
                        progress = currentUpdaterState.progress,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(6.dp),
                        color = Blue400,
                        trackColor = Surface600
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "${(currentUpdaterState.progress * 100).toInt()}% completed",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.White
                    )
                }
            },
            confirmButton = {},
            containerColor = Surface800,
            shape = RoundedCornerShape(16.dp)
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "DeviceLink",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                            color = Color.White,
                        )
                        Text(
                            text = "Local Network Devices",
                            style = MaterialTheme.typography.labelSmall,
                            color = OnSurfaceDim,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface800,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                actions = {
                    IconButton(onClick = onSettingsClicked) {
                        Icon(
                            imageVector = Icons.Default.Settings,
                            contentDescription = "Settings",
                            tint = Color.White
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = onManualScan,
                containerColor = Blue400,
                contentColor = Color.White,
                shape = RoundedCornerShape(16.dp)
            ) {
                Icon(
                    painter = androidx.compose.ui.res.painterResource(id = android.R.drawable.ic_menu_camera),
                    contentDescription = "Scan QR Manually"
                )
            }
        },
        containerColor = Surface900,
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = { viewModel.refresh() },
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (devices.isEmpty()) {
                EmptyDiscoveryState()
            } else {
                val activeFingerprint by viewModel.activeFingerprint.collectAsState()
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    contentPadding = PaddingValues(16.dp),
                ) {
                    itemsIndexed(devices) { index, device ->
                        val isConnected = device.fingerprint != null && device.fingerprint == activeFingerprint
                        AnimatedDeviceCard(
                            device = device,
                            index = index,
                            isConnected = isConnected,
                            onClick = { onDeviceSelected(device.host, device.port, device.isPaired, device.fingerprint) },
                        )
                    }
                }
            }
        }
    }
}

// ── Sub-components ────────────────────────────────────────────────────────────

@Composable
private fun AnimatedDeviceCard(
    device: NexusDevice,
    index: Int,
    isConnected: Boolean,
    onClick: () -> Unit,
) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(index * 60L)
        visible = true
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn() + slideInVertically { it / 3 },
    ) {
        DeviceCard(device = device, isConnected = isConnected, onClick = onClick)
    }
}

@Composable
private fun DeviceCard(device: NexusDevice, isConnected: Boolean, onClick: () -> Unit) {
    val cardModifier = if (isConnected) {
        val infiniteTransition = rememberInfiniteTransition(label = "glowTransition")
        val glowAlpha by infiniteTransition.animateFloat(
            initialValue = 0.2f,
            targetValue = 0.7f,
            animationSpec = infiniteRepeatable(
                animation = tween(1200, easing = LinearEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "glowAlpha"
        )
        val glowRadiusRaw by infiniteTransition.animateFloat(
            initialValue = 4f,
            targetValue = 8f,
            animationSpec = infiniteRepeatable(
                animation = tween(1200, easing = LinearEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "glowRadius"
        )
        val glowRadius = glowRadiusRaw.dp
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .border(glowRadius, Emerald400.copy(alpha = glowAlpha), RoundedCornerShape(16.dp))
            .padding(1.5.dp)
            .border(2.dp, Emerald400, RoundedCornerShape(16.dp))
    } else {
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .border(1.dp, Surface600, RoundedCornerShape(16.dp))
    }

    Card(
        modifier = cardModifier,
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Surface800),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Flat, solid computer icon block (replaces the pulsing gradient look)
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .background(Surface700, RoundedCornerShape(12.dp))
                    .border(1.dp, Surface600, RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = if (device.host == "cloud") Icons.Default.Cloud else Icons.Default.Computer,
                    contentDescription = null,
                    tint = if (device.host == "cloud") Cyan400 else Blue400,
                    modifier = Modifier.size(24.dp),
                )
            }

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = device.displayName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = "${device.host}:${device.port}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = OnSurfaceDim,
                )
                if (device.fingerprint != null) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "Fingerprint: ${device.fingerprint.take(12)}…",
                        style = MaterialTheme.typography.labelSmall,
                        color = Cyan400,
                        letterSpacing = 0.5.sp,
                    )
                }
            }

            // Clean modern badges (no generic templates)
            if (device.host == "cloud") {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        imageVector = Icons.Default.Cloud,
                        contentDescription = "Cloud Relay",
                        tint = Cyan400,
                        modifier = Modifier.size(20.dp),
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "CLOUD",
                        style = MaterialTheme.typography.labelSmall,
                        color = Cyan400,
                        fontWeight = FontWeight.Bold,
                        fontSize = 9.sp,
                    )
                }
            } else if (device.isPaired) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        imageVector = Icons.Default.Shield,
                        contentDescription = "Trusted",
                        tint = Emerald400,
                        modifier = Modifier.size(20.dp),
                    )
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = "TRUSTED",
                        style = MaterialTheme.typography.labelSmall,
                        color = Emerald400,
                        fontWeight = FontWeight.Bold,
                        fontSize = 9.sp,
                    )
                }
            } else {
                Icon(
                    imageVector = Icons.Default.Link,
                    contentDescription = "Connect",
                    tint = Blue400,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun EmptyDiscoveryState() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.padding(32.dp)
        ) {
            // Elegant, thin CircularProgressIndicator instead of pulsing magnifying glass
            CircularProgressIndicator(
                color = Blue400,
                strokeWidth = 3.dp,
                modifier = Modifier.size(48.dp)
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "Searching for PC Host...",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = Color.White,
            )
            Text(
                text = "Make sure the DeviceLink agent is running on your PC and both devices are on the same Wi-Fi network.",
                style = MaterialTheme.typography.bodyMedium,
                color = OnSurfaceDim,
                textAlign = TextAlign.Center,
                lineHeight = 20.sp
            )
        }
    }
}
