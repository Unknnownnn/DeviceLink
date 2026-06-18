@file:OptIn(androidx.compose.animation.ExperimentalSharedTransitionApi::class)
package com.nexuslink.app.ui.screens

import android.Manifest
import android.bluetooth.BluetoothProfile
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.animateColor
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.ui.zIndex
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationVector2D
import androidx.compose.animation.core.VectorConverter
import androidx.compose.animation.core.updateTransition
import androidx.compose.animation.core.animateDp
import androidx.compose.ui.composed
import androidx.compose.ui.layout.approachLayout
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import kotlin.random.Random
import kotlin.math.PI
import kotlin.math.sin
import kotlinx.coroutines.delay
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.layout.LookaheadScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.NightsStay
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import android.content.Intent
import androidx.hilt.navigation.compose.hiltViewModel
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.ui.theme.*
import com.nexuslink.app.ui.viewmodels.ConnectionViewModel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.collectLatest
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionScreen(
    host: String,
    port: Int,
    fingerprint: String,
    onDisconnect: () -> Unit,
    viewModel: ConnectionViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val desktopDeck by viewModel.desktopDeck.collectAsState()
    val context = LocalContext.current

    var hasConnectedBefore by remember { mutableStateOf(false) }

    LaunchedEffect(uiState.connectionState) {
        if (uiState.connectionState is ConnectionState.Connected) {
            hasConnectedBefore = true
        } else if (hasConnectedBefore && (uiState.connectionState is ConnectionState.Disconnected || uiState.connectionState is ConnectionState.Error)) {
            // We were connected, but got disconnected/error! Pop screen to scanning.
            onDisconnect()
        }
    }

    var nlpPrompt by remember { mutableStateOf("") }
    var nlpResponseDialogText by remember { mutableStateOf<String?>(null) }
    var showChatHistoryDialog by remember { mutableStateOf(false) }
    var isAiThinking by remember { mutableStateOf(false) }

    // ── Runtime permissions for phone state, calls & contacts ──────────────────────
    val permissionsLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* handle results silently; Bluetooth checked separately */ }

    LaunchedEffect(Unit) {
        val permsNeeded = buildList {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_PHONE_STATE)
                != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.READ_PHONE_STATE)
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS)
                != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.READ_CONTACTS)
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE)
                != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.CALL_PHONE)
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALL_LOG)
                != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.READ_CALL_LOG)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if (ContextCompat.checkSelfPermission(context, "android.permission.ANSWER_PHONE_CALLS")
                    != PackageManager.PERMISSION_GRANTED) add("android.permission.ANSWER_PHONE_CALLS")
            }
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.S_V2) { // Android 12L (API 32) and lower
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_EXTERNAL_STORAGE)
                    != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (ContextCompat.checkSelfPermission(context, "android.permission.BLUETOOTH_CONNECT")
                    != PackageManager.PERMISSION_GRANTED) add("android.permission.BLUETOOTH_CONNECT")
                if (ContextCompat.checkSelfPermission(context, "android.permission.BLUETOOTH_SCAN")
                    != PackageManager.PERMISSION_GRANTED) add("android.permission.BLUETOOTH_SCAN")
            }
        }
        if (permsNeeded.isNotEmpty()) permissionsLauncher.launch(permsNeeded.toTypedArray())
    }

    val filePickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            viewModel.sendFile(uri)
        }
    }

    LaunchedEffect(Unit) {
        viewModel.connect(host, port, fingerprint)
    }

    LaunchedEffect(viewModel.nlpResponses) {
        viewModel.nlpResponses.collect { response ->
            nlpResponseDialogText = response
            isAiThinking = false
        }
    }

    LaunchedEffect(Unit) {
        viewModel.toastEvents.collectLatest { msg ->
            Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Session: $host", style = MaterialTheme.typography.titleLarge) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface800,
                    titleContentColor = OnSurface
                ),
                actions = {
                    IconButton(onClick = {
                        viewModel.disconnect()
                        onDisconnect()
                    }) {
                        Icon(Icons.Default.Close, contentDescription = "Disconnect")
                    }
                }
            )
        },
        containerColor = Surface900
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentAlignment = Alignment.Center
        ) {
            AnimatedContent(
                targetState = uiState.connectionState,
                modifier = Modifier.fillMaxSize(),
                label = "conn_state"
            ) { state ->
                when (state) {
                    is ConnectionState.Disconnected -> {
                        if (uiState.connectionPhase.isEmpty()) {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.Center,
                                modifier = Modifier.fillMaxSize().padding(16.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Close,
                                    contentDescription = "Disconnected",
                                    tint = OnSurfaceDim,
                                    modifier = Modifier.size(48.dp)
                                )
                                Spacer(modifier = Modifier.height(16.dp))
                                Text(
                                    text = "Disconnected",
                                    style = MaterialTheme.typography.titleLarge,
                                    fontWeight = FontWeight.Bold,
                                    color = OnSurface
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = "Connection lost or could not be established.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = OnSurfaceDim,
                                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                                )
                                Spacer(modifier = Modifier.height(24.dp))
                                Button(
                                    onClick = { viewModel.connect(host, port, fingerprint) },
                                    colors = ButtonDefaults.buttonColors(containerColor = Blue400),
                                    modifier = Modifier.fillMaxWidth(0.6f)
                                ) {
                                    Text("Retry Connection", color = OnSurface)
                                }
                                Spacer(modifier = Modifier.height(8.dp))
                                TextButton(
                                    onClick = { onDisconnect() }
                                ) {
                                    Text("Go Back to List", color = OnSurfaceDim)
                                }
                            }
                        } else {
                            Column(
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.Center,
                                modifier = Modifier.fillMaxSize()
                            ) {
                                ConnectionLoader()
                                Spacer(modifier = Modifier.height(24.dp))
                                Text(
                                    text = "Connecting...",
                                    style = MaterialTheme.typography.titleLarge,
                                    fontWeight = FontWeight.Bold,
                                    color = OnSurface
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = uiState.connectionPhase,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = OnSurfaceDim,
                                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                                )
                            }
                        }
                    }
                    is ConnectionState.Connecting, is ConnectionState.Handshaking -> {
                        val statusTitle = if (state is ConnectionState.Handshaking) "Handshaking..." else "Connecting..."
                        val statusSubtitle = if (uiState.connectionPhase.isNotEmpty()) {
                            uiState.connectionPhase
                        } else if (state is ConnectionState.Handshaking) {
                            "Performing X25519 ECDH key exchange"
                        } else {
                            "Establishing socket to $host:$port"
                        }
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center,
                            modifier = Modifier.fillMaxSize()
                        ) {
                            ConnectionLoader()
                            Spacer(modifier = Modifier.height(24.dp))
                            Text(
                                text = statusTitle,
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold,
                                color = OnSurface
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = statusSubtitle,
                                style = MaterialTheme.typography.bodyMedium,
                                color = OnSurfaceDim,
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center
                            )
                        }
                    }
                    is ConnectionState.Error -> {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center,
                            modifier = Modifier.fillMaxSize().padding(16.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.Error,
                                contentDescription = "Error",
                                tint = MaterialTheme.colorScheme.error,
                                modifier = Modifier.size(48.dp)
                            )
                            Spacer(modifier = Modifier.height(16.dp))
                            Text(
                                text = "Connection Failed",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold,
                                color = OnSurface
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = state.message,
                                style = MaterialTheme.typography.bodyMedium,
                                color = OnSurfaceDim,
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center
                            )
                            Spacer(modifier = Modifier.height(24.dp))
                            Button(
                                onClick = { viewModel.connect(host, port, fingerprint) },
                                colors = ButtonDefaults.buttonColors(containerColor = Rose400),
                                modifier = Modifier.fillMaxWidth(0.6f)
                            ) {
                                Text("Retry Connection", color = OnSurface)
                            }
                            Spacer(modifier = Modifier.height(8.dp))
                            TextButton(
                                onClick = { onDisconnect() }
                            ) {
                                Text("Go Back to List", color = OnSurfaceDim)
                            }
                        }
                    }
                    is ConnectionState.Connected -> {
                        data class SectionTab(val name: String)
                        var tabs by remember {
                            mutableStateOf(
                                listOf(
                                    SectionTab("AI"),
                                    SectionTab("Apps"),
                                    SectionTab("Power"),
                                    SectionTab("App Link")
                                )
                            )
                        }
                        val activeSection = tabs[0].name
                        var showAppSelectionDialog by remember { mutableStateOf(false) }
                        var isLogsExpanded by remember { mutableStateOf(false) }

                        var isNotificationAccessGranted by remember { mutableStateOf(false) }
                        var isOverlayPermissionGranted by remember { mutableStateOf(false) }
                        val isMiuiDevice = remember { checkIsMiuiDevice(context) }
                        var isMiuiPopupPermissionGranted by remember { mutableStateOf(true) }
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
                                    isMiuiPopupPermissionGranted = isMiuiBackgroundStartActivityAllowed(context)
                                }
                            }
                            lifecycleOwner.lifecycle.addObserver(observer)
                            onDispose {
                                lifecycleOwner.lifecycle.removeObserver(observer)
                            }
                        }

                        DisposableEffect(activeSection) {
                            if (activeSection == "App Link") {
                                viewModel.setLogsSubscription(true)
                            } else {
                                viewModel.setLogsSubscription(false)
                            }
                            onDispose {
                                if (activeSection == "App Link") {
                                    viewModel.setLogsSubscription(false)
                                }
                            }
                        }

                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(horizontal = 24.dp, vertical = 8.dp)
                                .verticalScroll(rememberScrollState())
                        ) {
                            var isDismissedNotifWarning by remember { mutableStateOf(false) }
                            if (!isNotificationAccessGranted && !isDismissedNotifWarning) {
                                var isExpandedWarning by remember { mutableStateOf(false) }
                                Card(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 16.dp, vertical = 4.dp)
                                        .animateContentSize(),
                                    colors = CardDefaults.cardColors(containerColor = Rose900.copy(alpha = 0.85f)),
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Column(modifier = Modifier.fillMaxWidth()) {
                                        Row(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .clickable { isExpandedWarning = !isExpandedWarning }
                                                .padding(horizontal = 12.dp, vertical = 8.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                                        ) {
                                            Icon(
                                                imageVector = Icons.Default.Error,
                                                contentDescription = "Warning",
                                                tint = Rose400,
                                                modifier = Modifier.size(18.dp)
                                            )
                                            Text(
                                                text = "Notification Access Required",
                                                color = Color.White,
                                                fontWeight = FontWeight.Bold,
                                                style = MaterialTheme.typography.bodyMedium,
                                                modifier = Modifier.weight(1f)
                                            )
                                            Icon(
                                                imageVector = if (isExpandedWarning) androidx.compose.material.icons.Icons.Default.KeyboardArrowUp else androidx.compose.material.icons.Icons.Default.KeyboardArrowDown,
                                                contentDescription = "Expand",
                                                tint = Color.White,
                                                modifier = Modifier.size(20.dp)
                                            )
                                            IconButton(
                                                onClick = { isDismissedNotifWarning = true },
                                                modifier = Modifier.size(28.dp)
                                            ) {
                                                Icon(
                                                    imageVector = androidx.compose.material.icons.Icons.Default.Close,
                                                    contentDescription = "Dismiss",
                                                    tint = Color.White.copy(alpha = 0.7f),
                                                    modifier = Modifier.size(16.dp)
                                                )
                                            }
                                        }

                                        if (isExpandedWarning) {
                                            Column(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(horizontal = 12.dp)
                                                    .padding(bottom = 12.dp),
                                                verticalArrangement = Arrangement.spacedBy(8.dp)
                                            ) {
                                                Text(
                                                    text = "This app needs notification listener access to sync notifications to your PC.",
                                                    color = OnSurfaceDim,
                                                    style = MaterialTheme.typography.bodySmall
                                                )
                                                Button(
                                                    onClick = {
                                                        try {
                                                            val intent = android.content.Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS").apply {
                                                                addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                                                            }
                                                            context.startActivity(intent)
                                                        } catch (e: Exception) {
                                                            android.widget.Toast.makeText(context, "Could not open settings: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
                                                        }
                                                    },
                                                    colors = ButtonDefaults.buttonColors(containerColor = Rose400),
                                                    modifier = Modifier.fillMaxWidth(),
                                                    shape = RoundedCornerShape(6.dp)
                                                ) {
                                                    Text("Grant Notification Access", color = Color.White, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                                                }
                                                HorizontalDivider(color = Surface600.copy(alpha = 0.5f), thickness = 1.dp)
                                                Text(
                                                    text = "If the toggle is greyed out (Android 13+), allow restricted settings first:",
                                                    color = OnSurfaceDim,
                                                    style = MaterialTheme.typography.bodySmall
                                                )
                                                Button(
                                                    onClick = {
                                                        try {
                                                            val intent = android.content.Intent(
                                                                android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                                                android.net.Uri.parse("package:${context.packageName}")
                                                            ).apply { addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK) }
                                                            context.startActivity(intent)
                                                        } catch (e: Exception) {
                                                            android.widget.Toast.makeText(context, "Could not open App Info: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
                                                        }
                                                    },
                                                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF59E0B)),
                                                    modifier = Modifier.fillMaxWidth(),
                                                    shape = RoundedCornerShape(6.dp)
                                                ) {
                                                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                                        Icon(Icons.Default.Lock, contentDescription = null, tint = Color.Black, modifier = Modifier.size(16.dp))
                                                        Text("Allow Restricted Settings", color = Color.Black, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                                                    }
                                                }
                                                Text(
                                                    text = "Tap ⋮ in top-right of App Info → 'Allow restricted settings', then come back and grant access above.",
                                                    color = OnSurfaceDim,
                                                    style = MaterialTheme.typography.bodySmall
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                            val secColor: (String) -> Color = {
                                when(it) {
                                    "AI" -> Rose400
                                    "Apps" -> Blue400
                                    "Power" -> Emerald400
                                    else -> Color(0xFFF59E0B)
                                }
                            }

                             // Quick-action buttons — always visible above the fan stack
                             Row(
                                 modifier = Modifier.fillMaxWidth(),
                                 horizontalArrangement = Arrangement.spacedBy(12.dp)
                             ) {
                                 Button(
                                     onClick = { viewModel.pushClipboardToPc() },
                                     modifier = Modifier.weight(1f),
                                     colors = ButtonDefaults.buttonColors(containerColor = Blue500, contentColor = Color.White),
                                     shape = RoundedCornerShape(12.dp)
                                 ) { Text("Push Clipboard", maxLines = 1) }
                                 Button(
                                     onClick = { filePickerLauncher.launch("*/*") },
                                     modifier = Modifier.weight(1f),
                                     colors = ButtonDefaults.buttonColors(containerColor = Blue400, contentColor = Color.White),
                                     shape = RoundedCornerShape(12.dp)
                                 ) { Text("Send File", maxLines = 1) }
                             }
                             Spacer(modifier = Modifier.height(16.dp))

                             // Fan-stack card layout
                             Box(
                                 modifier = Modifier
                                     .fillMaxWidth()
                                     .height(660.dp)
                              ) {
                                 tabs.reversed().forEachIndexed { reversedIndex, tab ->
                                 key(tab.name) {
                                     val actualIndex = tabs.lastIndex - reversedIndex
                                     val section = tab.name
                                     val isActive = actualIndex == 0
                                     val icon = when (section) {
                                         "AI" -> Icons.Default.Sync
                                         "Apps" -> Icons.Default.Apps
                                         "Power" -> Icons.Default.PowerSettingsNew
                                         else -> Icons.Default.PlayArrow
                                     }

                                     val transition = updateTransition(
                                         targetState = isActive,
                                         label = "cardTransition_$section"
                                     )

                                     val top by transition.animateDp(
                                         label = "top_$section",
                                         transitionSpec = { tween(durationMillis = 500, easing = FastOutSlowInEasing) }
                                     ) { active ->
                                         if (active) 0.dp
                                         else when (actualIndex) {
                                             1 -> 470.dp
                                             2 -> 535.dp
                                             else -> 600.dp
                                         }
                                     }

                                     val cardHeight by transition.animateDp(
                                         label = "height_$section",
                                         transitionSpec = { tween(durationMillis = 500, easing = FastOutSlowInEasing) }
                                     ) { active ->
                                         if (active) 490.dp else 90.dp
                                     }

                                     val rotation by transition.animateFloat(
                                         label = "rotation_$section",
                                         transitionSpec = { tween(durationMillis = 500, easing = FastOutSlowInEasing) }
                                     ) { active ->
                                         if (active) 0f
                                         else when (actualIndex) {
                                             1 -> 3f
                                             2 -> 0f
                                             else -> -3f
                                         }
                                     }

                                     val elevation by transition.animateDp(
                                         label = "elevation_$section",
                                         transitionSpec = { tween(durationMillis = 500, easing = FastOutSlowInEasing) }
                                     ) { active ->
                                         if (active) 12.dp else 4.dp
                                     }

                                     val bgColor by animateColorAsState(
                                         targetValue = if (isActive) Surface800 else secColor(section),
                                         animationSpec = tween(durationMillis = 500, easing = FastOutSlowInEasing),
                                         label = "bg_color_$section"
                                     )

                                     val borderStroke = if (isActive) BorderStroke(1.5.dp, secColor(section)) else null

                                     Card(
                                         modifier = Modifier
                                             .fillMaxWidth()
                                             .padding(horizontal = 8.dp)
                                             .offset(y = top)
                                             .height(cardHeight)
                                             .graphicsLayer { rotationZ = rotation }
                                             .zIndex(if (isActive) 10f else (tabs.size - actualIndex).toFloat())
                                             .clickable(
                                                 enabled = !isActive,
                                                 interactionSource = remember { MutableInteractionSource() },
                                                 indication = null
                                             ) {
                                                 if (!isActive) {
                                                     val selected = tabs[actualIndex]
                                                     tabs = buildList {
                                                         add(selected)
                                                         addAll(tabs.filterIndexed { i, _ -> i != actualIndex })
                                                     }
                                                 }
                                             },
                                         colors = CardDefaults.cardColors(containerColor = bgColor),
                                         border = borderStroke,
                                         elevation = CardDefaults.cardElevation(defaultElevation = elevation),
                                         shape = RoundedCornerShape(24.dp)
                                     ) {
                                         if (isActive) {
                                             Column(
                                                 modifier = Modifier
                                                     .fillMaxSize()
                                                     .padding(16.dp)
                                             ) {
                                                 Row(
                                                     modifier = Modifier.fillMaxWidth(),
                                                     verticalAlignment = Alignment.CenterVertically
                                                 ) {
                                                     Icon(
                                                         imageVector = icon,
                                                         contentDescription = null,
                                                         tint = secColor(section),
                                                         modifier = Modifier.size(24.dp)
                                                     )
                                                     Spacer(modifier = Modifier.width(12.dp))
                                                     Text(
                                                         text = section,
                                                         color = secColor(section),
                                                         style = MaterialTheme.typography.titleMedium,
                                                         fontWeight = FontWeight.Bold
                                                     )
                                                 }

                                                 Spacer(modifier = Modifier.height(8.dp))

                                                 Column(
                                                     modifier = Modifier
                                                         .weight(1f)
                                                         .fillMaxWidth()
                                                         .verticalScroll(rememberScrollState())
                                                 ) {
                                                         Spacer(modifier = Modifier.height(8.dp))
                                                         when (section) {
                                                             "AI" -> {
                                                                 if (isAiThinking) {
                                                                     AIThinkingWave(
                                                                         modifier = Modifier
                                                                             .fillMaxWidth()
                                                                             .height(260.dp)
                                                                             .clip(RoundedCornerShape(12.dp))
                                                                     )
                                                                 } else {
                                                                     OutlinedTextField(
                                                                         value = nlpPrompt,
                                                                         onValueChange = { nlpPrompt = it },
                                                                         label = { Text("Command") },
                                                                         modifier = Modifier.fillMaxWidth(),
                                                                         colors = OutlinedTextFieldDefaults.colors(
                                                                             focusedBorderColor = Rose400,
                                                                             unfocusedBorderColor = Surface600,
                                                                             focusedTextColor = Color.White,
                                                                             unfocusedTextColor = Color.White
                                                                         )
                                                                     )
                                                                     Spacer(modifier = Modifier.height(8.dp))
                                                                     Row(
                                                                         modifier = Modifier.fillMaxWidth(),
                                                                         horizontalArrangement = Arrangement.spacedBy(8.dp)
                                                                     ) {
                                                                         Button(
                                                                             onClick = {
                                                                                 if (nlpPrompt.isNotBlank()) {
                                                                                     isAiThinking = true
                                                                                     viewModel.sendNlpCommand(nlpPrompt)
                                                                                     nlpPrompt = ""
                                                                                 }
                                                                             },
                                                                             modifier = Modifier.weight(1f),
                                                                             colors = ButtonDefaults.buttonColors(containerColor = Rose500)
                                                                         ) { Text("Execute") }
                                                                         Button(
                                                                             onClick = { showChatHistoryDialog = true },
                                                                             modifier = Modifier.weight(1f),
                                                                             colors = ButtonDefaults.buttonColors(containerColor = Surface600)
                                                                         ) { Text("Chat History") }
                                                                     }
                                                                 }
                                                             }
                                                             "Apps" -> {
                                                                 val shortcuts = viewModel.deckShortcuts.collectAsState().value
                                                                 if (shortcuts.isNotEmpty()) {
                                                                     Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                                                                         val chunks = shortcuts.chunked(3)
                                                                         for (chunk in chunks) {
                                                                             Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                                                                 for (shortcut in chunk) {
                                                                                     val label = shortcut.optString("label", "App")
                                                                                     val id = shortcut.optString("id", "")
                                                                                     val type = shortcut.optString("type", "app")
                                                                                     val iconB64 = shortcut.optString("icon", "")
                                                                                     val shortcutIcon = if (type == "steam") Icons.Default.PlayArrow else Icons.Default.Apps
                                                                                     DeckButton(label = label, icon = shortcutIcon, iconB64 = iconB64, color = Blue500) { viewModel.launchApp(id) }
                                                                                 }
                                                                                 repeat(3 - chunk.size) { Spacer(modifier = Modifier.size(72.dp)) }
                                                                             }
                                                                             Spacer(modifier = Modifier.height(16.dp))
                                                                         }
                                                                     }
                                                                 } else {
                                                                     Text("No apps", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                                                 }
                                                             }
                                                             "Power" -> {
                                                                 Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                                                                     Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                                                         DeckButton("Lock", Icons.Default.Lock, color = Emerald500) { viewModel.sendPowerCommand("lock") }
                                                                         DeckButton("Sleep", Icons.Default.NightsStay, color = Emerald500) { viewModel.sendPowerCommand("sleep") }
                                                                     }
                                                                     Spacer(modifier = Modifier.height(16.dp))
                                                                     Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                                                         DeckButton("Restart", Icons.Default.Sync, color = Rose500) { viewModel.sendPowerCommand("restart") }
                                                                         DeckButton("Shutdown", Icons.Default.PowerSettingsNew, color = Rose500) { viewModel.sendPowerCommand("shutdown") }
                                                                     }
                                                                 }
                                                             }
                                                             "App Link" -> {
                                                                 Column(horizontalAlignment = Alignment.Start, modifier = Modifier.fillMaxWidth()) {
                                                                     if (!isOverlayPermissionGranted) {
                                                                         var isExpandedOverlayWarning by remember { mutableStateOf(false) }
                                                                         Card(
                                                                             modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp).animateContentSize(),
                                                                             colors = CardDefaults.cardColors(containerColor = Rose900.copy(alpha = 0.85f)),
                                                                             shape = RoundedCornerShape(8.dp)
                                                                         ) {
                                                                             Column(modifier = Modifier.fillMaxWidth()) {
                                                                                 Row(
                                                                                     modifier = Modifier.fillMaxWidth().clickable { isExpandedOverlayWarning = !isExpandedOverlayWarning }.padding(horizontal = 12.dp, vertical = 8.dp),
                                                                                     verticalAlignment = Alignment.CenterVertically,
                                                                                     horizontalArrangement = Arrangement.spacedBy(8.dp)
                                                                                 ) {
                                                                                     Icon(Icons.Default.Error, contentDescription = null, tint = Rose400, modifier = Modifier.size(18.dp))
                                                                                     Text("Background Launch Required", color = Color.White, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                                                                                     Icon(if (isExpandedOverlayWarning) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                                                 }
                                                                                 if (isExpandedOverlayWarning) {
                                                                                     Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                                                         Text("To allow launching apps from your PC while this app is in the background, please enable 'Display over other apps' permission.", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                                                                         Button(
                                                                                             onClick = {
                                                                                                 try {
                                                                                                     context.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION, android.net.Uri.parse("package:${context.packageName}")).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                                                                                                 } catch (e: Exception) {
                                                                                                     try { context.startActivity(Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }) } catch (ex: Exception) { android.widget.Toast.makeText(context, "Could not open settings", android.widget.Toast.LENGTH_SHORT).show() }
                                                                                                 }
                                                                                             },
                                                                                             colors = ButtonDefaults.buttonColors(containerColor = Rose400),
                                                                                             modifier = Modifier.fillMaxWidth(),
                                                                                             shape = RoundedCornerShape(6.dp)
                                                                                         ) { Text("Grant Permission", color = Color.White, fontWeight = FontWeight.Bold) }
                                                                                     }
                                                                                 }
                                                                             }
                                                                         }
                                                                     }
                                                                     if (isOverlayPermissionGranted && isMiuiDevice && !isMiuiPopupPermissionGranted) {
                                                                         var isExpandedMiuiWarning by remember { mutableStateOf(false) }
                                                                         Card(
                                                                             modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp).animateContentSize(),
                                                                             colors = CardDefaults.cardColors(containerColor = Rose900.copy(alpha = 0.85f)),
                                                                             shape = RoundedCornerShape(8.dp)
                                                                         ) {
                                                                             Column(modifier = Modifier.fillMaxWidth()) {
                                                                                 Row(
                                                                                     modifier = Modifier.fillMaxWidth().clickable { isExpandedMiuiWarning = !isExpandedMiuiWarning }.padding(horizontal = 12.dp, vertical = 8.dp),
                                                                                     verticalAlignment = Alignment.CenterVertically,
                                                                                     horizontalArrangement = Arrangement.spacedBy(8.dp)
                                                                                 ) {
                                                                                     Icon(Icons.Default.Error, contentDescription = null, tint = Rose400, modifier = Modifier.size(18.dp))
                                                                                     Text("MIUI Background Pop-up Required", color = Color.White, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                                                                                     Icon(if (isExpandedMiuiWarning) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp))
                                                                                 }
                                                                                 if (isExpandedMiuiWarning) {
                                                                                     Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).padding(bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                                                         Text("MIUI/HyperOS requires granting 'Display pop-up windows while running in background' under Other Permissions.", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                                                                         Button(onClick = { openMiuiPermissionSettings(context) }, colors = ButtonDefaults.buttonColors(containerColor = Rose400), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(6.dp)) { Text("Grant Permission", color = Color.White, fontWeight = FontWeight.Bold) }
                                                                                     }
                                                                                 }
                                                                             }
                                                                         }
                                                                     }
                                                                     if (showAppSelectionDialog) {
                                                                         val pm = context.packageManager
                                                                         val installedApps = remember {
                                                                             pm.queryIntentActivities(android.content.Intent(android.content.Intent.ACTION_MAIN, null).apply { addCategory(android.content.Intent.CATEGORY_LAUNCHER) }, 0)
                                                                                 .map { Pair(it.loadLabel(pm).toString(), it.activityInfo.packageName) }
                                                                                 .sortedBy { it.first.lowercase() }
                                                                         }
                                                                         AlertDialog(
                                                                             onDismissRequest = { showAppSelectionDialog = false },
                                                                             title = { Text("Add App to Desktop Deck") },
                                                                             text = {
                                                                                 LazyColumn(modifier = Modifier.heightIn(max = 280.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                                                     items(installedApps) { app ->
                                                                                         val isAlreadyAdded = desktopDeck.any { it.optString("package") == app.second }
                                                                                         Row(
                                                                                             modifier = Modifier.fillMaxWidth().clickable(enabled = !isAlreadyAdded) {
                                                                                                 viewModel.saveDesktopDeckApps(desktopDeck + org.json.JSONObject().apply { put("label", app.first); put("package", app.second) })
                                                                                                 showAppSelectionDialog = false
                                                                                             }.padding(vertical = 8.dp, horizontal = 12.dp),
                                                                                             verticalAlignment = Alignment.CenterVertically,
                                                                                             horizontalArrangement = Arrangement.SpaceBetween
                                                                                         ) {
                                                                                             Text(app.first, color = if (isAlreadyAdded) OnSurfaceDim else Color.White, style = MaterialTheme.typography.bodyLarge)
                                                                                             if (isAlreadyAdded) Text("Added", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                                                                         }
                                                                                     }
                                                                                 }
                                                                             },
                                                                             confirmButton = { TextButton(onClick = { showAppSelectionDialog = false }) { Text("Close", color = Rose400) } },
                                                                             containerColor = Surface800, titleContentColor = Color.White, textContentColor = Color.White
                                                                         )
                                                                     }
                                                                     Text("Desktop Deck Apps (${desktopDeck.size}/10)", color = Color.White, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                                                                     Spacer(modifier = Modifier.height(8.dp))
                                                                     if (desktopDeck.isEmpty()) {
                                                                         Text("No apps in desktop deck yet.", color = OnSurfaceDim, style = MaterialTheme.typography.bodyMedium)
                                                                     } else {
                                                                         Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                                             for (rowApps in desktopDeck.chunked(2)) {
                                                                                 Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                                                                     for (app in rowApps) {
                                                                                         val label = app.optString("label", "App")
                                                                                         val pkg = app.optString("package", "")
                                                                                         Card(
                                                                                             colors = CardDefaults.cardColors(containerColor = Surface800),
                                                                                             modifier = Modifier.weight(1f).clickable {
                                                                                                 try {
                                                                                                     val li = context.packageManager.getLaunchIntentForPackage(pkg)
                                                                                                     if (li != null) context.startActivity(li) else android.widget.Toast.makeText(context, "Cannot launch", android.widget.Toast.LENGTH_SHORT).show()
                                                                                                 } catch (e: Exception) { android.widget.Toast.makeText(context, "Error: ${e.message}", android.widget.Toast.LENGTH_SHORT).show() }
                                                                                             },
                                                                                             shape = RoundedCornerShape(8.dp)
                                                                                         ) {
                                                                                             Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                                                                                                 Text(if (label.length > 12) label.take(10) + ".." else label, color = Color.White, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                                                                                                 IconButton(onClick = { viewModel.saveDesktopDeckApps(desktopDeck.filter { it.optString("package") != pkg }) }, modifier = Modifier.size(24.dp)) {
                                                                                                     Icon(androidx.compose.material.icons.Icons.Default.Close, contentDescription = "Remove", tint = Rose400, modifier = Modifier.size(16.dp))
                                                                                                 }
                                                                                             }
                                                                                         }
                                                                                     }
                                                                                     if (rowApps.size == 1) Spacer(modifier = Modifier.weight(1f))
                                                                                 }
                                                                             }
                                                                         }
                                                                     }
                                                                     if (desktopDeck.size < 10) {
                                                                         Spacer(modifier = Modifier.height(8.dp))
                                                                         Button(onClick = { showAppSelectionDialog = true }, colors = ButtonDefaults.buttonColors(containerColor = Blue400), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp)) { Text("+ Add App to Desktop Deck", color = Color.White) }
                                                                     }
                                                                     Spacer(modifier = Modifier.height(16.dp))
                                                                     HorizontalDivider(color = Surface600, thickness = 1.dp)
                                                                     Spacer(modifier = Modifier.height(12.dp))
                                                                     Row(
                                                                         modifier = Modifier.fillMaxWidth().clickable { isLogsExpanded = !isLogsExpanded }.padding(vertical = 4.dp),
                                                                         verticalAlignment = Alignment.CenterVertically,
                                                                         horizontalArrangement = Arrangement.SpaceBetween
                                                                     ) {
                                                                         Text("System Logs (ChaCha20-Poly1305)", color = Color(0xFFF59E0B), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                                                                         Icon(if (isLogsExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown, contentDescription = null, tint = Color(0xFFF59E0B), modifier = Modifier.size(20.dp))
                                                                     }
                                                                     Spacer(modifier = Modifier.height(8.dp))
                                                                     if (isLogsExpanded) {
                                                                         Box(modifier = Modifier.fillMaxWidth().height(160.dp).background(Surface900, RoundedCornerShape(8.dp)).border(1.dp, Surface600, RoundedCornerShape(8.dp)).padding(12.dp)) {
                                                                             val scrollState = rememberScrollState()
                                                                             LaunchedEffect(uiState.logs.size) { scrollState.animateScrollTo(scrollState.maxValue) }
                                                                             Column(modifier = Modifier.verticalScroll(scrollState)) {
                                                                                 if (uiState.logs.isEmpty()) {
                                                                                     Text("No logs yet. Establish connection to begin.", color = OnSurfaceDim, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                                                                                 } else {
                                                                                     uiState.logs.forEach { log -> Text(log, color = Color(0xFFF59E0B), fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 2.dp)) }
                                                                                 }
                                                                             }
                                                                         }
                                                                     }
                                                                 }
                                                             }
                                                         }
                                                     }
                                             }
                                         } else {
                                             // Inactive card — show icon + label
                                             Row(
                                                 modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp),
                                                 verticalAlignment = Alignment.CenterVertically
                                             ) {
                                                 Icon(imageVector = icon, contentDescription = null, tint = Color.White.copy(alpha = 0.9f), modifier = Modifier.size(22.dp))
                                                 Spacer(modifier = Modifier.width(14.dp))
                                                 Text(text = section, color = Color.White, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                                             }
                                         }
                                     }
                                 }
                                  }
                             }


                        }
                    }
                }
            }
        }
    }

    if (nlpResponseDialogText != null) {
        val hasError = remember(nlpResponseDialogText) {
            val txt = nlpResponseDialogText!!.lowercase()
            txt.contains("error") || txt.contains("failed") || txt.contains("timeout") || txt.contains("failure") || txt.contains("prohibited")
        }
        AlertDialog(
            onDismissRequest = { nlpResponseDialogText = null },
            title = { Text("AI Execution Result") },
            text = { Text(nlpResponseDialogText ?: "") },
            dismissButton = if (hasError) {
                {
                    TextButton(onClick = {
                        isAiThinking = true
                        viewModel.retryLastNlpCommand()
                        nlpResponseDialogText = null
                    }) {
                        Text("Retry", color = Rose400)
                    }
                }
            } else null,
            confirmButton = {
                TextButton(onClick = { nlpResponseDialogText = null }) {
                    Text("Close")
                }
            }
        )
    }

    if (showChatHistoryDialog) {
        val chatHistory by viewModel.aiChatHistory.collectAsState()
        AlertDialog(
            onDismissRequest = { showChatHistoryDialog = false },
            title = { Text("AI Chat History", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) },
            text = {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(350.dp)
                ) {
                    if (chatHistory.isEmpty()) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("No chat history in this session", color = OnSurfaceDim)
                        }
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            verticalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            items(chatHistory) { chat ->
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .background(Surface800, RoundedCornerShape(8.dp))
                                        .border(1.dp, Surface600, RoundedCornerShape(8.dp))
                                        .padding(12.dp)
                                ) {
                                    Text(
                                        text = "Prompt:",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Rose400,
                                        fontWeight = FontWeight.Bold
                                    )
                                    Text(
                                        text = chat.prompt,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = Color.White,
                                        modifier = Modifier.padding(bottom = 8.dp)
                                    )
                                    
                                    HorizontalDivider(color = Surface600.copy(alpha = 0.5f))
                                    Spacer(modifier = Modifier.height(8.dp))
                                    
                                    Text(
                                        text = "Response:",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Blue400,
                                        fontWeight = FontWeight.Bold
                                    )
                                    val isErr = remember(chat.response) {
                                        val txt = chat.response.lowercase()
                                        txt.contains("error") || txt.contains("failed") || txt.contains("timeout") || txt.contains("failure") || txt.contains("prohibited")
                                    }
                                    Text(
                                        text = chat.response,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = if (isErr) Rose400 else OnSurfaceDim
                                    )
                                    if (isErr) {
                                        Spacer(modifier = Modifier.height(8.dp))
                                        TextButton(
                                            onClick = {
                                                isAiThinking = true
                                                viewModel.sendNlpCommand(chat.prompt)
                                                showChatHistoryDialog = false
                                            },
                                            contentPadding = PaddingValues(0.dp)
                                        ) {
                                            Text("Retry this command", color = Rose400, style = MaterialTheme.typography.labelSmall)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showChatHistoryDialog = false }) {
                    Text("Close")
                }
            },
            dismissButton = if (chatHistory.isNotEmpty()) {
                {
                    TextButton(onClick = {
                        viewModel.clearChatHistory()
                    }) {
                        Text("Clear History", color = Rose400)
                    }
                }
            } else null,
            containerColor = Surface900
        )
    }
}

@Composable
private fun StatusBanner(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    iconTint: Color,
    title: String,
    subtitle: String,
    containerColor: Color,
    borderColor: Color = Color.Transparent
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(containerColor)
            .border(1.dp, borderColor, RoundedCornerShape(16.dp))
            .padding(24.dp)
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.fillMaxWidth()
        ) {
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .background(iconTint.copy(alpha = 0.15f), CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Icon(icon, contentDescription = null, tint = iconTint, modifier = Modifier.size(32.dp))
            }
            Spacer(modifier = Modifier.height(16.dp))
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = OnSurface)
            Spacer(modifier = Modifier.height(4.dp))
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = OnSurfaceDim, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
}

@Composable
private fun Metric(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.displayMedium, color = Cyan400)
        Text(label, style = MaterialTheme.typography.labelSmall, color = OnSurfaceDim)
    }
}

@Composable
private fun DeckButton(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    iconB64: String = "",
    color: Color,
    onClick: () -> Unit
) {
    val imageBitmap = remember(iconB64) {
        if (iconB64.isNotEmpty()) {
            try {
                val decodedBytes = android.util.Base64.decode(iconB64, android.util.Base64.DEFAULT)
                android.graphics.BitmapFactory.decodeByteArray(decodedBytes, 0, decodedBytes.size)?.asImageBitmap()
            } catch (e: Exception) {
                null
            }
        } else {
            null
        }
    }

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Button(
            onClick = onClick,
            modifier = Modifier.size(72.dp),
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (imageBitmap != null) Surface800 else color
            ),
            contentPadding = PaddingValues(0.dp)
        ) {
            if (imageBitmap != null) {
                androidx.compose.foundation.Image(
                    bitmap = imageBitmap,
                    contentDescription = label,
                    modifier = Modifier.fillMaxSize().padding(14.dp)
                )
            } else {
                Icon(icon, contentDescription = label, modifier = Modifier.size(32.dp))
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = OnSurface)
    }
}

@Composable
fun ExpandableGridItem(
    title: String,
    color: Color,
    expanded: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val transition = updateTransition(targetState = expanded, label = "expand_grid_item")

    val topPadding by transition.animateDp(
        label = "top_padding",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) 16.dp else 8.dp
    }

    val bottomPadding by transition.animateDp(
        label = "bottom_padding",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) 16.dp else 8.dp
    }

    val horizontalPadding by transition.animateDp(
        label = "horizontal_padding",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) 16.dp else 8.dp
    }

    val topSpacerHeight by transition.animateDp(
        label = "top_spacer",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) 0.dp else 6.dp
    }

    val backgroundColor by transition.animateColor(
        label = "background_color",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) Surface800 else color
    }

    val contentColor by transition.animateColor(
        label = "content_color",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) color else Surface900
    }

    val borderColor by transition.animateColor(
        label = "border_color",
        transitionSpec = { tween(durationMillis = 400, easing = FastOutSlowInEasing) }
    ) { state ->
        if (state) color else color
    }

    Box(
        modifier = modifier
            .background(backgroundColor, RoundedCornerShape(16.dp))
            .border(1.dp, borderColor, RoundedCornerShape(16.dp))
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick
            )
            .padding(
                start = horizontalPadding,
                end = horizontalPadding,
                top = topPadding,
                bottom = bottomPadding
            ),
        contentAlignment = Alignment.TopCenter
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .fillMaxWidth()
                .then(
                    if (expanded) Modifier.verticalScroll(rememberScrollState()) else Modifier
                )
        ) {
            Spacer(modifier = Modifier.height(topSpacerHeight))
            Text(
                title,
                color = contentColor,
                style = if (expanded) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center
            )
            transition.AnimatedVisibility(
                visible = { it },
                enter = fadeIn(
                    animationSpec = tween(
                        durationMillis = 300,
                        delayMillis = 100,
                        easing = FastOutSlowInEasing
                    )
                ),
                exit = fadeOut(
                    animationSpec = tween(
                        durationMillis = 150,
                        easing = FastOutSlowInEasing
                    )
                )
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Spacer(modifier = Modifier.height(16.dp))
                    content()
                }
            }
        }
    }
}

@Composable
fun ConnectionLoader(
    modifier: Modifier = Modifier,
) {
    val infiniteTransition = rememberInfiniteTransition(label = "")

    val ring1 = infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 4000

                0f at 0
                1f at 1000     // draw
                1f at 2000     // hold
                0f at 3000     // erase
                0f at 4000
            }
        ),
        label = ""
    )

    val ring2 = infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 4000

                0f at 0
                0f at 500
                1f at 1500
                1f at 2500
                0f at 3500
                0f at 4000
            }
        ),
        label = ""
    )

    val ring3 = infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 4000

                0f at 0
                0f at 1000
                1f at 2000
                1f at 3000
                0f at 4000
            }
        ),
        label = ""
    )

    Box(
        modifier = modifier.size(220.dp),
        contentAlignment = Alignment.Center
    ) {
        Canvas(
            modifier = Modifier.fillMaxSize()
        ) {

            drawAnimatedRing(
                radius = 40.dp.toPx(),
                progress = ring1.value,
                color = Color(0xFF00E5FF),
                strokeWidth = 8.dp.toPx()
            )

            drawAnimatedRing(
                radius = 60.dp.toPx(),
                progress = ring2.value,
                color = Color(0xFF7C4DFF),
                strokeWidth = 8.dp.toPx()
            )

            drawAnimatedRing(
                radius = 80.dp.toPx(),
                progress = ring3.value,
                color = Color(0xFF00FF95),
                strokeWidth = 8.dp.toPx()
            )
        }
    }
}

private fun DrawScope.drawAnimatedRing(
    radius: Float,
    progress: Float,
    color: Color,
    strokeWidth: Float
) {
    val center = center

    val sweep = 360f * progress

    drawArc(
        color = color,
        startAngle = -90f,
        sweepAngle = sweep,
        useCenter = false,
        topLeft = Offset(
            center.x - radius,
            center.y - radius
        ),
        size = Size(
            radius * 2,
            radius * 2
        ),
        style = Stroke(
            width = strokeWidth,
            cap = StrokeCap.Round
        )
    )
}

@Composable
fun AIThinkingWave(
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(
        label = "wave"
    )

    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = (2f * PI).toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(
                durationMillis = 3500,
                easing = LinearEasing
            )
        ),
        label = "phase"
    )

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black),
        contentAlignment = Alignment.Center
    ) {
        Canvas(
            modifier = Modifier
                .width(260.dp)
                .height(140.dp)
        ) {
            val barCount = 15
            val spacing = size.width / barCount
            val minHeight = 14f
            val maxHeight = 110f

            repeat(barCount) { index ->
                val x = index * spacing
                val wave = ((sin(phase + index * 0.55f) + 1f) / 2f)
                val height = minHeight + wave * (maxHeight - minHeight)
                val width = 10f

                drawRoundRect(
                    color = Color(0xFF00E5FF),
                    topLeft = Offset(x, (size.height - height) / 2f),
                    size = Size(width, height),
                    cornerRadius = CornerRadius(width, width)
                )
            }
        }

        Text(
            text = "THINKING",
            color = Color.White.copy(alpha = 0.6f),
            letterSpacing = 4.sp,
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 64.dp)
        )
    }
}


