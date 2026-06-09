package com.nexuslink.app.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.ui.theme.Cyan400
import com.nexuslink.app.ui.theme.Emerald400
import com.nexuslink.app.ui.theme.Indigo800
import com.nexuslink.app.ui.theme.OnSurfaceDim
import com.nexuslink.app.ui.theme.Surface600
import com.nexuslink.app.ui.theme.Surface700
import com.nexuslink.app.ui.theme.Surface800
import com.nexuslink.app.ui.theme.Violet400
import com.nexuslink.app.ui.theme.Violet200
import com.nexuslink.app.ui.viewmodels.DiscoveryViewModel
import kotlinx.coroutines.delay

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
    viewModel: DiscoveryViewModel = hiltViewModel(),
) {
    val devices by viewModel.devices.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "DeviceLink",
                            style = MaterialTheme.typography.headlineLarge,
                            fontWeight = FontWeight.Bold,
                            color = Violet200,
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
                    ScanningIndicator()
                    Spacer(Modifier.width(12.dp))
                },
            )
        },
        floatingActionButton = {
            androidx.compose.material3.FloatingActionButton(
                onClick = onManualScan,
                containerColor = Violet400,
                contentColor = Color.White
            ) {
                Icon(
                    painter = androidx.compose.ui.res.painterResource(id = android.R.drawable.ic_menu_camera),
                    contentDescription = "Scan QR Manually"
                )
            }
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            if (devices.isEmpty()) {
                EmptyDiscoveryState()
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                ) {
                    itemsIndexed(devices) { index, device ->
                        AnimatedDeviceCard(
                            device = device,
                            index = index,
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
private fun ScanningIndicator() {
    val infiniteTransition = rememberInfiniteTransition(label = "scan_pulse")
    val scale by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 1.2f,
        animationSpec = infiniteRepeatable(
            animation = tween(800, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse_scale",
    )

    Box(
        modifier = Modifier
            .size(36.dp)
            .scale(scale)
            .background(Cyan400.copy(alpha = 0.15f), CircleShape)
            .border(1.dp, Cyan400.copy(alpha = 0.5f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Default.Wifi,
            contentDescription = "Scanning",
            tint = Cyan400,
            modifier = Modifier.size(18.dp),
        )
    }
}

@Composable
private fun AnimatedDeviceCard(
    device: NexusDevice,
    index: Int,
    onClick: () -> Unit,
) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(index * 80L)
        visible = true
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn() + slideInVertically { it / 2 },
    ) {
        DeviceCard(device = device, onClick = onClick)
    }
}

@Composable
private fun DeviceCard(device: NexusDevice, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Surface700),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.horizontalGradient(
                        colors = listOf(
                            Indigo800.copy(alpha = 0.5f),
                            Surface700,
                        )
                    )
                )
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // Device icon
                Box(
                    modifier = Modifier
                        .size(52.dp)
                        .background(
                            Brush.radialGradient(
                                colors = listOf(Violet400.copy(alpha = 0.3f), Color.Transparent)
                            ),
                            CircleShape,
                        )
                        .border(1.dp, Violet400.copy(alpha = 0.4f), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.Computer,
                        contentDescription = null,
                        tint = Violet400,
                        modifier = Modifier.size(28.dp),
                    )
                }

                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = device.displayName,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
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
                            text = "fp: ${device.fingerprint.take(12)}…",
                            style = MaterialTheme.typography.labelSmall,
                            color = Cyan400,
                            letterSpacing = 0.5.sp,
                        )
                    }
                }

                // Paired badge or connect arrow
                if (device.isPaired) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(
                            imageVector = Icons.Default.Shield,
                            contentDescription = "Paired",
                            tint = Emerald400,
                            modifier = Modifier.size(22.dp),
                        )
                        Text(
                            text = "TRUSTED",
                            style = MaterialTheme.typography.labelSmall,
                            color = Emerald400,
                            fontSize = 9.sp,
                        )
                    }
                } else {
                    Icon(
                        imageVector = Icons.Default.Link,
                        contentDescription = "Connect",
                        tint = Violet400,
                        modifier = Modifier.size(22.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyDiscoveryState() {
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "alpha",
    )

    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(100.dp)
                    .background(
                        Violet400.copy(alpha = alpha * 0.15f),
                        CircleShape,
                    )
                    .border(2.dp, Violet400.copy(alpha = alpha * 0.5f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Default.Search,
                    contentDescription = null,
                    tint = Violet400.copy(alpha = alpha),
                    modifier = Modifier.size(48.dp),
                )
            }
            Text(
                text = "Scanning for Devices…",
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Make sure your PC agent is running\nand connected to the same network",
                style = MaterialTheme.typography.bodyMedium,
                color = OnSurfaceDim,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}
