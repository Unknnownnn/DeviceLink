package com.nexuslink.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.nexuslink.app.BuildConfig
import com.nexuslink.app.ui.theme.*
import android.widget.Toast
import com.nexuslink.app.ui.viewmodels.SettingsViewModel
import com.nexuslink.app.updater.GitHubUpdater
import com.nexuslink.app.updater.UpdaterState
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val updater = remember { GitHubUpdater(context) }
    val updaterState by updater.state.collectAsState()

    val trustedPeers by viewModel.trustedPeers.collectAsState()
    val autoConnectEnabled by viewModel.autoConnectEnabled.collectAsState()
    val preferredFp by viewModel.preferredAutoConnectFingerprint.collectAsState()

    LaunchedEffect(updaterState) {
        if (updaterState is UpdaterState.UpToDate) {
            Toast.makeText(context, "No new updates found", Toast.LENGTH_SHORT).show()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "Settings",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = Color.White
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            tint = Color.White
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface800
                )
            )
        },
        containerColor = Surface900
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // App Info Card
            Card(
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = Surface800),
                modifier = Modifier
                    .fillMaxWidth()
                    .border(1.dp, Surface600, RoundedCornerShape(16.dp))
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(48.dp)
                            .background(Blue400.copy(alpha = 0.15f), RoundedCornerShape(12.dp))
                            .border(1.dp, Blue400.copy(alpha = 0.3f), RoundedCornerShape(12.dp)),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.Info,
                            contentDescription = null,
                            tint = Blue400,
                            modifier = Modifier.size(24.dp)
                        )
                    }
                    Column {
                        Text(
                            text = "DeviceLink Companion",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                        Spacer(modifier = Modifier.height(2.dp))
                        Text(
                            text = "Version ${BuildConfig.VERSION_NAME}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = OnSurfaceDim
                        )
                    }
                }
            }

            // Auto-Connect Settings Card
            Card(
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = Surface800),
                modifier = Modifier
                    .fillMaxWidth()
                    .border(1.dp, Surface600, RoundedCornerShape(16.dp))
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Computer,
                            contentDescription = null,
                            tint = Blue400,
                            modifier = Modifier.size(22.dp)
                        )
                        Text(
                            text = "Auto-Connect Settings",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                    }

                    Divider(color = Surface600, thickness = 1.dp)

                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "Auto-Connect to PC",
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = FontWeight.Bold,
                                color = Color.White
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Automatically connect to a verified PC when found on the network.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = OnSurfaceDim
                            )
                        }
                        Spacer(modifier = Modifier.width(16.dp))
                        Switch(
                            checked = autoConnectEnabled,
                            onCheckedChange = { viewModel.setAutoConnectEnabled(it) },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = Color.White,
                                checkedTrackColor = Blue400,
                                uncheckedThumbColor = OnSurfaceDim,
                                uncheckedTrackColor = Surface600
                            )
                        )
                    }

                    if (autoConnectEnabled && trustedPeers.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Choose PC to Auto-Connect to:",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = Color.White
                        )

                        // List of trusted peers
                        trustedPeers.values.forEach { peer ->
                            val isSelected = preferredFp == peer.fingerprint || (trustedPeers.size == 1 && preferredFp == null)
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        viewModel.setPreferredAutoConnectFingerprint(peer.fingerprint)
                                    }
                                    .background(
                                        if (isSelected) Blue400.copy(alpha = 0.15f) else Color.Transparent,
                                        RoundedCornerShape(8.dp)
                                    )
                                    .border(
                                        1.dp,
                                        if (isSelected) Blue400 else Color.Transparent,
                                        RoundedCornerShape(8.dp)
                                    )
                                    .padding(12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = peer.displayName,
                                        style = MaterialTheme.typography.bodyLarge,
                                        fontWeight = FontWeight.Bold,
                                        color = Color.White
                                    )
                                    Text(
                                        text = "Fingerprint: ${peer.fingerprint.take(12)}…",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = OnSurfaceDim
                                    )
                                }
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    RadioButton(
                                        selected = isSelected,
                                        onClick = { viewModel.setPreferredAutoConnectFingerprint(peer.fingerprint) },
                                        colors = RadioButtonDefaults.colors(
                                            selectedColor = Blue400,
                                            unselectedColor = Surface600
                                        )
                                    )
                                    IconButton(
                                        onClick = { viewModel.removeTrustedPeer(peer.fingerprint) },
                                        modifier = Modifier.size(36.dp)
                                    ) {
                                        Icon(
                                            imageVector = Icons.Default.Delete,
                                            contentDescription = "Delete Device",
                                            tint = Rose400,
                                            modifier = Modifier.size(20.dp)
                                        )
                                    }
                                }
                            }
                        }
                    } else if (autoConnectEnabled && trustedPeers.isEmpty()) {
                        Text(
                            text = "No verified PCs yet. Pair a PC via QR scanner first.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Rose400
                        )
                    }
                }
            }

            // Updates Card
            Card(
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = Surface800),
                modifier = Modifier
                    .fillMaxWidth()
                    .border(1.dp, Surface600, RoundedCornerShape(16.dp))
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.SystemUpdate,
                            contentDescription = null,
                            tint = Blue400,
                            modifier = Modifier.size(22.dp)
                        )
                        Text(
                            text = "App Updates",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                    }

                    Divider(color = Surface600, thickness = 1.dp)

                    // Dynamic state handling
                    when (val state = updaterState) {
                        is UpdaterState.Idle -> {
                            Text(
                                text = "Check for updates from the official GitHub releases.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = OnSurfaceDim
                            )
                            Button(
                                onClick = {
                                    scope.launch { updater.checkForUpdates(force = true) }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = Blue400),
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text("Check for Updates", color = Color.White)
                            }
                        }
                        is UpdaterState.Checking -> {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                CircularProgressIndicator(color = Blue400, modifier = Modifier.size(24.dp))
                                Spacer(modifier = Modifier.width(12.dp))
                                Text("Checking GitHub...", color = Color.White)
                            }
                        }
                        is UpdaterState.UpdateAvailable -> {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text(
                                    text = "Update Available: ${state.latestVersion}",
                                    color = Emerald400,
                                    fontWeight = FontWeight.Bold,
                                    style = MaterialTheme.typography.bodyLarge
                                )
                                Text(
                                    text = "A newer build is ready on GitHub. Tap below to download and self-install app-debug.apk.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = OnSurfaceDim
                                )
                                Button(
                                    onClick = {
                                        scope.launch { updater.downloadAndInstall(state.downloadUrl) }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = Emerald400),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("Download & Install", color = Color.Black)
                                }
                            }
                        }
                        is UpdaterState.Downloading -> {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("Downloading Update...", color = Color.White)
                                LinearProgressIndicator(
                                    progress = state.progress,
                                    modifier = Modifier.fillMaxWidth(),
                                    color = Blue400,
                                    trackColor = Surface600
                                )
                                Text(
                                    text = "${(state.progress * 100).toInt()}% completed",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = OnSurfaceDim,
                                    modifier = Modifier.align(Alignment.End)
                                )
                            }
                        }
                        is UpdaterState.ReadyToInstall -> {
                            Text(
                                text = "Preparing package installation...",
                                color = Emerald400,
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                        is UpdaterState.UpToDate -> {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text(
                                    text = "DeviceLink is up-to-date!",
                                    color = Emerald400,
                                    fontWeight = FontWeight.Bold,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                Button(
                                    onClick = {
                                        scope.launch { updater.checkForUpdates(force = true) }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = Surface700),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("Check Again", color = Color.White)
                                }
                            }
                        }
                        is UpdaterState.Error -> {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text(
                                    text = "Error: ${state.message}",
                                    color = Rose400,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                Button(
                                    onClick = {
                                        scope.launch { updater.checkForUpdates(force = true) }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = Blue400),
                                    shape = RoundedCornerShape(8.dp),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text("Retry", color = Color.White)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
