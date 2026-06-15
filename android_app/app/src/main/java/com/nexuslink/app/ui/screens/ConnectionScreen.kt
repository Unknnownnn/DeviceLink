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
import androidx.compose.animation.core.tween
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.nexuslink.app.network.ConnectionState
import com.nexuslink.app.ui.theme.*
import com.nexuslink.app.ui.viewmodels.ConnectionViewModel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.collectLatest

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
    val context = LocalContext.current

    var nlpPrompt by remember { mutableStateOf("") }
    var nlpResponseDialogText by remember { mutableStateOf<String?>(null) }
    var showChatHistoryDialog by remember { mutableStateOf(false) }

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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            AnimatedContent(targetState = uiState.connectionState, label = "conn_state") { state ->
                when (state) {
                    is ConnectionState.Disconnected, is ConnectionState.Connecting -> {
                        StatusBanner(
                            icon = Icons.Default.Sync,
                            iconTint = Cyan400,
                            title = "Connecting...",
                            subtitle = "Establishing socket to $host:$port",
                            containerColor = Surface800
                        )
                    }
                    is ConnectionState.Handshaking -> {
                        StatusBanner(
                            icon = Icons.Default.Sync,
                            iconTint = Blue400,
                            title = "Handshaking...",
                            subtitle = "Performing X25519 ECDH key exchange",
                            containerColor = Surface800
                        )
                    }
                    is ConnectionState.Connected -> {
                        val sections = remember { listOf("AI", "Apps", "Power", "Logs") }
                        var activeSection by remember { mutableStateOf("AI") }
                        var expandedSection by remember { mutableStateOf("AI") }

                        DisposableEffect(activeSection) {
                            if (activeSection == "Logs") {
                                viewModel.setLogsSubscription(true)
                            } else {
                                viewModel.setLogsSubscription(false)
                            }
                            onDispose {
                                if (activeSection == "Logs") {
                                    viewModel.setLogsSubscription(false)
                                }
                            }
                        }
                        LaunchedEffect(activeSection) {
                            if (activeSection != expandedSection) {
                                expandedSection = ""
                                kotlinx.coroutines.delay(200)
                                expandedSection = activeSection
                            }
                        }

                        val isExpanded = activeSection == expandedSection
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(vertical = 16.dp)
                        ) {
                            val secColor: (String) -> Color = {
                                when(it) {
                                    "AI" -> Rose400
                                    "Apps" -> Blue400
                                    "Power" -> Emerald400
                                    else -> Color(0xFFF59E0B) // Amber/Yellow
                                }
                            }

                             // TOP CARD (Active tab, animated)
                            ExpandableGridItem(
                                title = activeSection,
                                color = secColor(activeSection),
                                expanded = isExpanded,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .animateContentSize(
                                        animationSpec = tween(
                                            durationMillis = 400,
                                            easing = FastOutSlowInEasing
                                        )
                                    )
                                    .height(if (isExpanded) 420.dp else 64.dp),
                                onClick = { }
                            ) {
                                when (activeSection) {
                                    "AI" -> {
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
                                                        viewModel.sendNlpCommand(nlpPrompt)
                                                        nlpPrompt = ""
                                                    }
                                                },
                                                modifier = Modifier.weight(1f),
                                                colors = ButtonDefaults.buttonColors(containerColor = Rose500)
                                            ) {
                                                Text("Execute")
                                            }
                                            Button(
                                                onClick = {
                                                    showChatHistoryDialog = true
                                                },
                                                modifier = Modifier.weight(1f),
                                                colors = ButtonDefaults.buttonColors(containerColor = Surface600)
                                            ) {
                                                Text("Chat History")
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
                                                            val icon = if (type == "steam") Icons.Default.PlayArrow else Icons.Default.Apps
                                                            DeckButton(
                                                                label = label,
                                                                icon = icon,
                                                                iconB64 = iconB64,
                                                                color = Blue500
                                                            ) {
                                                                viewModel.launchApp(id)
                                                            }
                                                        }
                                                        repeat(3 - chunk.size) {
                                                            Spacer(modifier = Modifier.size(72.dp))
                                                        }
                                                    }
                                                    Spacer(modifier = Modifier.height(16.dp))
                                                }
                                            }
                                        } else {
                                            Text("No apps", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                        }
                                    }
                                    "Power" -> {
                                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                            DeckButton("Lock", Icons.Default.Lock, color = Emerald500) { viewModel.sendPowerCommand("lock") }
                                            DeckButton("Sleep", Icons.Default.NightsStay, color = Emerald500) { viewModel.sendPowerCommand("sleep") }
                                            DeckButton("Shutdown", Icons.Default.PowerSettingsNew, color = Rose500) { viewModel.sendPowerCommand("shutdown") }
                                        }
                                    }
                                    "Logs" -> {
                                        Column(
                                            horizontalAlignment = Alignment.Start,
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Text(
                                                text = "System Logs (ChaCha20-Poly1305)",
                                                color = Color(0xFFF59E0B),
                                                style = MaterialTheme.typography.bodyMedium,
                                                fontWeight = FontWeight.Bold
                                            )
                                            Spacer(modifier = Modifier.height(12.dp))

                                            // Console-style Log Container
                                            Box(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .height(280.dp)
                                                    .background(Surface900, RoundedCornerShape(8.dp))
                                                    .border(1.dp, Surface600, RoundedCornerShape(8.dp))
                                                    .padding(12.dp)
                                            ) {
                                                val scrollState = rememberScrollState()
                                                LaunchedEffect(uiState.logs.size) {
                                                    scrollState.animateScrollTo(scrollState.maxValue)
                                                }
                                                Column(modifier = Modifier.verticalScroll(scrollState)) {
                                                    if (uiState.logs.isEmpty()) {
                                                        Text(
                                                            text = "No logs yet. Establish connection to begin.",
                                                            color = OnSurfaceDim,
                                                            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                                            style = MaterialTheme.typography.bodySmall
                                                        )
                                                    } else {
                                                        uiState.logs.forEach { log ->
                                                            Text(
                                                                text = log,
                                                                color = Color(0xFFF59E0B),
                                                                fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                                                style = MaterialTheme.typography.bodySmall,
                                                                modifier = Modifier.padding(bottom = 2.dp)
                                                            )
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // SPACER THAT DYNAMICALLY EXPANDS TO FILL SPACE WHEN COLLAPSED
                            Spacer(
                                modifier = Modifier.weight(1f)
                            )

                            // FIXED BOTTOM ROW
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(64.dp),
                                horizontalArrangement = Arrangement.spacedBy(12.dp)
                            ) {
                                val inactiveSecs = sections.filter { it != activeSection }
                                inactiveSecs.forEach { sec ->
                                    ExpandableGridItem(
                                        title = sec,
                                        color = secColor(sec),
                                        expanded = false,
                                        modifier = Modifier
                                            .weight(1f)
                                            .fillMaxHeight(),
                                        onClick = {
                                            activeSection = sec
                                        }
                                    ) {
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(24.dp))
                            Button(
                                onClick = { viewModel.pushClipboardToPc() },
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.buttonColors(containerColor = Blue500, contentColor = Color.White)
                            ) {
                                Text("Push Phone Clipboard to PC")
                            }
                            Spacer(modifier = Modifier.height(12.dp))
                            Button(
                                onClick = { filePickerLauncher.launch("*/*") },
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.buttonColors(containerColor = Blue400, contentColor = Color.White)
                            ) {
                                Text("Send File to PC")
                            }
                        }
                    }
                    is ConnectionState.Error -> {
                        StatusBanner(
                            icon = Icons.Default.Error,
                            iconTint = Rose500,
                            title = "Connection Failed",
                            subtitle = state.message,
                            containerColor = Rose500.copy(alpha = 0.1f),
                            borderColor = Rose500.copy(alpha = 0.3f)
                        )
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
