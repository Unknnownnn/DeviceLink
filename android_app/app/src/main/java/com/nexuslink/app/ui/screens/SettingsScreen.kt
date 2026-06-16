package com.nexuslink.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.*
import android.content.Intent
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

    var isNotificationAccessGranted by remember { mutableStateOf(false) }
    var isOverlayPermissionGranted by remember { mutableStateOf(false) }
    var isPhonePermissionGranted by remember { mutableStateOf(false) }
    var isSmsPermissionGranted by remember { mutableStateOf(false) }
    var isContactsPermissionGranted by remember { mutableStateOf(false) }
    var isBluetoothPermissionGranted by remember { mutableStateOf(false) }
    var isCameraPermissionGranted by remember { mutableStateOf(false) }
    var isMiuiPopupPermissionGranted by remember { mutableStateOf(true) }
    var isPermissionsExpanded by remember { mutableStateOf(false) }

    val isMiuiDevice = remember { checkIsMiuiDevice(context) }

    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_RESUME) {
                val flat = android.provider.Settings.Secure.getString(
                    context.contentResolver,
                    "enabled_notification_listeners"
                )
                isNotificationAccessGranted = flat != null && flat.contains(context.packageName)
                isOverlayPermissionGranted = android.provider.Settings.canDrawOverlays(context)
                isPhonePermissionGranted = context.checkSelfPermission(android.Manifest.permission.READ_PHONE_STATE) == android.content.pm.PackageManager.PERMISSION_GRANTED
                isSmsPermissionGranted = context.checkSelfPermission(android.Manifest.permission.READ_SMS) == android.content.pm.PackageManager.PERMISSION_GRANTED
                isContactsPermissionGranted = context.checkSelfPermission(android.Manifest.permission.READ_CONTACTS) == android.content.pm.PackageManager.PERMISSION_GRANTED
                isBluetoothPermissionGranted = if (android.os.Build.VERSION.SDK_INT >= 31) {
                    context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_CONNECT) == android.content.pm.PackageManager.PERMISSION_GRANTED
                } else {
                    true
                }
                isCameraPermissionGranted = context.checkSelfPermission(android.Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED
                isMiuiPopupPermissionGranted = isMiuiBackgroundStartActivityAllowed(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

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
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // App Info & Updates Card
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

                    HorizontalDivider(color = Surface600, thickness = 1.dp)

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
                                    style = MaterialTheme.typography.bodyMedium
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

            // Battery & Sync Settings Card
            var isFeaturesExpanded by remember { mutableStateOf(false) }
            val batterySaverEnabled by viewModel.batterySaverEnabled.collectAsState()
            val bgLaunchEnabled by viewModel.bgLaunchEnabled.collectAsState()
            val notifSyncEnabled by viewModel.notifSyncEnabled.collectAsState()
            val phoneSyncEnabled by viewModel.phoneSyncEnabled.collectAsState()

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
                            imageVector = Icons.Default.PowerSettingsNew,
                            contentDescription = null,
                            tint = Color(0xFFF59E0B),
                            modifier = Modifier.size(22.dp)
                        )
                        Text(
                            text = "Battery & Sync Settings",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                    }

                    HorizontalDivider(color = Surface600, thickness = 1.dp)

                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "Battery Saver Mode",
                                style = MaterialTheme.typography.bodyLarge,
                                fontWeight = FontWeight.Bold,
                                color = Color.White
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Pause non-essential background features (App Launching, Notification reads, Status Sync) to maximize battery. Essential services remain active.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = OnSurfaceDim
                            )
                        }
                        Spacer(modifier = Modifier.width(16.dp))
                        Switch(
                            checked = batterySaverEnabled,
                            onCheckedChange = { viewModel.setBatterySaverEnabled(it) },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = Color.White,
                                checkedTrackColor = Color(0xFFF59E0B),
                                uncheckedThumbColor = OnSurfaceDim,
                                uncheckedTrackColor = Surface600
                            )
                        )
                    }

                    // Collapsible Header for Individual Feature Toggles
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { isFeaturesExpanded = !isFeaturesExpanded }
                            .padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = "Configure Specific Features",
                            color = if (batterySaverEnabled) OnSurfaceDim else Color.White,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Icon(
                            imageVector = if (isFeaturesExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                            contentDescription = "Expand Toggles",
                            tint = if (batterySaverEnabled) OnSurfaceDim else Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }

                    if (isFeaturesExpanded) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            // Toggle 1: Background App Launching
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "Background App Launching",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                        color = if (batterySaverEnabled) OnSurfaceDim else Color.White
                                    )
                                    Text(
                                        text = "Allow PC to trigger and launch apps on your device in the background.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = OnSurfaceDim
                                    )
                                }
                                Spacer(modifier = Modifier.width(16.dp))
                                Switch(
                                    checked = if (batterySaverEnabled) false else bgLaunchEnabled,
                                    enabled = !batterySaverEnabled,
                                    onCheckedChange = { viewModel.setBgLaunchEnabled(it) },
                                    colors = SwitchDefaults.colors(
                                        checkedThumbColor = Color.White,
                                        checkedTrackColor = Blue400,
                                        uncheckedThumbColor = OnSurfaceDim,
                                        uncheckedTrackColor = Surface600
                                    )
                                )
                            }

                            HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)

                            // Toggle 2: Notification Syncing
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "Notification Syncing",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                        color = if (batterySaverEnabled) OnSurfaceDim else Color.White
                                    )
                                    Text(
                                        text = "Read and forward notification tray events to your PC.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = OnSurfaceDim
                                    )
                                }
                                Spacer(modifier = Modifier.width(16.dp))
                                Switch(
                                    checked = if (batterySaverEnabled) false else notifSyncEnabled,
                                    enabled = !batterySaverEnabled,
                                    onCheckedChange = { viewModel.setNotifSyncEnabled(it) },
                                    colors = SwitchDefaults.colors(
                                        checkedThumbColor = Color.White,
                                        checkedTrackColor = Blue400,
                                        uncheckedThumbColor = OnSurfaceDim,
                                        uncheckedTrackColor = Surface600
                                    )
                                )
                            }

                            HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)

                            // Toggle 3: Phone Status Syncing
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = "Status & Wallpaper Syncing",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                        color = if (batterySaverEnabled) OnSurfaceDim else Color.White
                                    )
                                    Text(
                                        text = "Constant synchronization of battery, DND state, ringer mode, and wallpaper colors.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = OnSurfaceDim
                                    )
                                }
                                Spacer(modifier = Modifier.width(16.dp))
                                Switch(
                                    checked = if (batterySaverEnabled) false else phoneSyncEnabled,
                                    enabled = !batterySaverEnabled,
                                    onCheckedChange = { viewModel.setPhoneSyncEnabled(it) },
                                    colors = SwitchDefaults.colors(
                                        checkedThumbColor = Color.White,
                                        checkedTrackColor = Blue400,
                                        uncheckedThumbColor = OnSurfaceDim,
                                        uncheckedTrackColor = Surface600
                                    )
                                )
                            }
                        }
                    }
                }
            }

            // App Permissions Card
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
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { isPermissionsExpanded = !isPermissionsExpanded },
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.Shield,
                                contentDescription = null,
                                tint = Blue400,
                                modifier = Modifier.size(22.dp)
                            )
                            Text(
                                text = "App Permissions",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                                color = Color.White
                            )
                        }
                        Icon(
                            imageVector = if (isPermissionsExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                            contentDescription = "Expand Permissions",
                            tint = Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }

                    if (isPermissionsExpanded) {
                        HorizontalDivider(color = Surface600, thickness = 1.dp)

                        // 1. Notification Access
                        PermissionItem(
                            title = "Notification Access",
                            description = "Required to sync incoming phone notifications to your PC.",
                            isGranted = isNotificationAccessGranted,
                            onRequest = {
                                try {
                                    val intent = Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS").apply {
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    context.startActivity(intent)
                                } catch (e: Exception) {
                                    Toast.makeText(context, "Could not open settings", Toast.LENGTH_SHORT).show()
                                }
                            }
                        )

                        HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)

                        // 2. Display Over Other Apps (Overlay)
                        PermissionItem(
                            title = "Display Over Other Apps",
                            description = "Required to automatically launch apps from your PC while the device is in the background.",
                            isGranted = isOverlayPermissionGranted,
                            onRequest = {
                                try {
                                    val intent = Intent(
                                        android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                        android.net.Uri.parse("package:${context.packageName}")
                                    ).apply {
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    context.startActivity(intent)
                                } catch (e: Exception) {
                                    try {
                                        val intent = Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION).apply {
                                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                        }
                                        context.startActivity(intent)
                                    } catch (ex: Exception) {
                                        Toast.makeText(context, "Could not open settings", Toast.LENGTH_SHORT).show()
                                    }
                                }
                            }
                        )

                        // 3. MIUI Background Pop-up Permission (Only visible on MIUI/HyperOS devices)
                        if (isMiuiDevice) {
                            HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)
                            PermissionItem(
                                title = "MIUI Background Pop-up Permission",
                                description = "MIUI/HyperOS requires granting 'Display pop-up windows while running in background' under Other Permissions.",
                                isGranted = isMiuiPopupPermissionGranted,
                                customStatusText = if (isMiuiPopupPermissionGranted) "Granted" else "Action Required",
                                onRequest = {
                                    openMiuiPermissionSettings(context)
                                }
                            )
                        }

                        HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)

                        // 4. Runtime Permissions (Phone, SMS, Contacts, Bluetooth)
                        val allRuntimeGranted = isPhonePermissionGranted && isSmsPermissionGranted && isContactsPermissionGranted && isBluetoothPermissionGranted
                        PermissionItem(
                            title = "Sync & Calling Permissions",
                            description = "Access to Phone, SMS, Contacts and Bluetooth is needed to sync calls, SMS and Bluetooth status.",
                            isGranted = allRuntimeGranted,
                            customStatusText = if (allRuntimeGranted) "All Granted" else "Some Missing",
                            onRequest = {
                                try {
                                    val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                        data = android.net.Uri.fromParts("package", context.packageName, null)
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    context.startActivity(intent)
                                } catch (e: Exception) {
                                    Toast.makeText(context, "Could not open settings", Toast.LENGTH_SHORT).show()
                                }
                            }
                        )

                        HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 0.5.dp)

                        // 5. Camera Access
                        PermissionItem(
                            title = "Camera Access",
                            description = "Required to scan QR codes and pair your PC.",
                            isGranted = isCameraPermissionGranted,
                            onRequest = {
                                try {
                                    val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                        data = android.net.Uri.fromParts("package", context.packageName, null)
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    context.startActivity(intent)
                                } catch (e: Exception) {
                                    Toast.makeText(context, "Could not open settings", Toast.LENGTH_SHORT).show()
                                }
                            }
                        )
                    }
                }
            }


        }
    }
}

@Composable
private fun PermissionItem(
    title: String,
    description: String,
    isGranted: Boolean,
    customStatusText: String? = null,
    onRequest: () -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Bold,
                color = Color.White
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodyMedium,
                color = OnSurfaceDim
            )
            Spacer(modifier = Modifier.height(4.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Icon(
                    imageVector = if (isGranted) Icons.Default.CheckCircle else Icons.Default.Warning,
                    contentDescription = null,
                    tint = if (isGranted) Emerald400 else Rose400,
                    modifier = Modifier.size(14.dp)
                )
                Text(
                    text = customStatusText ?: (if (isGranted) "Granted" else "Not Granted"),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (isGranted) Emerald400 else Rose400,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }
        Spacer(modifier = Modifier.width(16.dp))
        Button(
            onClick = onRequest,
            colors = ButtonDefaults.buttonColors(
                containerColor = if (isGranted) Surface700 else Blue400
            ),
            shape = RoundedCornerShape(8.dp),
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
            modifier = Modifier.height(32.dp)
        ) {
            Text(
                text = if (isGranted) "Settings" else "Grant",
                color = Color.White,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
        }
    }
}
