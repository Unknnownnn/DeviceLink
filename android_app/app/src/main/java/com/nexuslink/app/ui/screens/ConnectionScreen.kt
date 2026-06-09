@file:OptIn(androidx.compose.animation.ExperimentalSharedTransitionApi::class)
package com.nexuslink.app.ui.screens

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationVector2D
import androidx.compose.animation.core.VectorConverter
import androidx.compose.ui.composed
import androidx.compose.ui.layout.approachLayout
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
                        var sectionsState by remember { mutableStateOf(listOf("AI", "Apps", "Power", "Logs")) }
                        var activeSection by remember { mutableStateOf(sectionsState.first()) }
                        
                        LookaheadScope {
                            Column(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .padding(vertical = 16.dp)
                            ) {
                                val activeSec = sectionsState.first { it == activeSection }
                                val inactiveSecs = sectionsState.filter { it != activeSection }
                                
                                val secColor: (String) -> Color = {
                                    when(it) {
                                        "AI" -> Rose400
                                        "Apps" -> Blue400
                                        "Power" -> Emerald400
                                        else -> Cyan400
                                    }
                                }

                                // TOP EXPANDED CARD
                                ExpandableGridItem(
                                    title = activeSec,
                                    color = secColor(activeSec),
                                    expanded = true,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .weight(0.6f)
                                        .animateBounds(lookaheadScope = this@LookaheadScope),
                                    onClick = { }
                                ) {
                                    when (activeSec) {
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
                                            Button(
                                                onClick = { 
                                                    if (nlpPrompt.isNotBlank()) {
                                                        viewModel.sendNlpCommand(nlpPrompt)
                                                        nlpPrompt = ""
                                                    }
                                                },
                                                modifier = Modifier.fillMaxWidth(),
                                                colors = ButtonDefaults.buttonColors(containerColor = Rose500)
                                            ) {
                                                Text("Execute")
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
                                                                val icon = if (type == "steam") Icons.Default.PlayArrow else Icons.Default.Apps
                                                                DeckButton(label, icon, Blue500) { viewModel.launchApp(id) }
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
                                                DeckButton("Lock", Icons.Default.Lock, Emerald500) { viewModel.sendPowerCommand("lock") }
                                                DeckButton("Sleep", Icons.Default.NightsStay, Emerald500) { viewModel.sendPowerCommand("sleep") }
                                                DeckButton("Shutdown", Icons.Default.PowerSettingsNew, Rose500) { viewModel.sendPowerCommand("shutdown") }
                                            }
                                        }
                                        "Logs" -> {
                                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                                StatusBanner(
                                                    icon = Icons.Default.CheckCircle,
                                                    iconTint = Emerald400,
                                                    title = "Secure Channel Active",
                                                    subtitle = "ChaCha20-Poly1305",
                                                    containerColor = Emerald400.copy(alpha = 0.1f),
                                                    borderColor = Emerald400.copy(alpha = 0.3f)
                                                )
                                                Spacer(modifier = Modifier.height(16.dp))
                                                Text("E2E Test", style = MaterialTheme.typography.titleSmall, color = Cyan200)
                                                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                                    Metric(label = "Pings", value = uiState.pingCount.toString())
                                                    Metric(label = "Pongs", value = uiState.pongCount.toString())
                                                }
                                                Spacer(modifier = Modifier.height(16.dp))
                                                Button(
                                                    onClick = { viewModel.sendPing() },
                                                    modifier = Modifier.fillMaxWidth(),
                                                    colors = ButtonDefaults.buttonColors(containerColor = Cyan500)
                                                ) {
                                                    Text("Ping")
                                                }
                                            }
                                        }
                                    }
                                }
                                
                                Spacer(Modifier.height(16.dp))
                                
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .weight(0.3f),
                                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                                ) {
                                    inactiveSecs.forEach { sec ->
                                        ExpandableGridItem(
                                            title = sec,
                                            color = secColor(sec),
                                            expanded = false,
                                            modifier = Modifier
                                                .weight(1f)
                                                .fillMaxHeight()
                                                .animateBounds(lookaheadScope = this@LookaheadScope),
                                            onClick = {
                                                val previousTop = sectionsState.first { it == activeSection }
                                                val clickedIndex = sectionsState.indexOfFirst { it == sec }
                                                val oldTopIndex = sectionsState.indexOfFirst { it == previousTop }
                                                
                                                val mutable = sectionsState.toMutableList()
                                                mutable[oldTopIndex] = sec
                                                mutable[clickedIndex] = previousTop
                                                sectionsState = mutable
                                                
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
        AlertDialog(
            onDismissRequest = { nlpResponseDialogText = null },
            title = { Text("AI Execution Result") },
            text = { Text(nlpResponseDialogText ?: "") },
            confirmButton = {
                TextButton(onClick = { nlpResponseDialogText = null }) {
                    Text("Close")
                }
            }
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
    color: Color, 
    onClick: () -> Unit
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Button(
            onClick = onClick,
            modifier = Modifier.size(72.dp),
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(containerColor = color),
            contentPadding = PaddingValues(0.dp)
        ) {
            Icon(icon, contentDescription = label, modifier = Modifier.size(32.dp))
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
    Box(
        modifier = modifier
            .background(color.copy(alpha = 0.2f), RoundedCornerShape(16.dp))
            .border(1.dp, color.copy(alpha = 0.4f), RoundedCornerShape(16.dp))
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = onClick
            )
            .padding(16.dp)
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally, 
            modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
        ) {
            Text(title, color = color, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            if (expanded) {
                Spacer(modifier = Modifier.height(16.dp))
                content()
            }
        }
    }
}

fun Modifier.animateBounds(
    lookaheadScope: LookaheadScope
): Modifier = this.composed {
    var sizeAnim by remember { mutableStateOf<Animatable<androidx.compose.ui.unit.IntSize, AnimationVector2D>?>(null) }
    var offsetAnim by remember { mutableStateOf<Animatable<androidx.compose.ui.unit.IntOffset, AnimationVector2D>?>(null) }
    val coroutineScope = rememberCoroutineScope()
    
    with(lookaheadScope) {
        this@composed.approachLayout(
            isMeasurementApproachInProgress = { lookaheadSize ->
                lookaheadSize != sizeAnim?.targetValue
            },
            isPlacementApproachInProgress = { lookaheadCoordinates ->
                val target = lookaheadScopeCoordinates.localLookaheadPositionOf(lookaheadCoordinates).let { 
                    androidx.compose.ui.unit.IntOffset(it.x.toInt(), it.y.toInt()) 
                }
                target != offsetAnim?.targetValue
            }
        ) { measurable, constraints ->
            val placeable = measurable.measure(constraints)
            
            val targetSize = androidx.compose.ui.unit.IntSize(lookaheadSize.width, lookaheadSize.height)
            val currentSizeAnim = sizeAnim ?: Animatable(targetSize, androidx.compose.ui.unit.IntSize.VectorConverter).also { sizeAnim = it }
            if (targetSize != currentSizeAnim.targetValue) {
                coroutineScope.launch { currentSizeAnim.animateTo(targetSize, tween(250, easing = FastOutSlowInEasing)) }
            }
            
            val size = currentSizeAnim.value
            
            layout(size.width, size.height) {
                val coords = coordinates
                if (coords != null) {
                    val targetOffset = lookaheadScopeCoordinates.localLookaheadPositionOf(coords).let { 
                        androidx.compose.ui.unit.IntOffset(it.x.toInt(), it.y.toInt()) 
                    }
                    val currentOffsetAnim = offsetAnim ?: Animatable(targetOffset, androidx.compose.ui.unit.IntOffset.VectorConverter).also { offsetAnim = it }
                    if (targetOffset != currentOffsetAnim.targetValue) {
                        coroutineScope.launch { currentOffsetAnim.animateTo(targetOffset, tween(250, easing = FastOutSlowInEasing)) }
                    }
                    
                    val currentOffset = lookaheadScopeCoordinates.localPositionOf(coords, androidx.compose.ui.geometry.Offset.Zero).let { 
                        androidx.compose.ui.unit.IntOffset(it.x.toInt(), it.y.toInt()) 
                    }
                    val offset = currentOffsetAnim.value - currentOffset
                    placeable.place(offset.x, offset.y)
                } else {
                    placeable.place(0, 0)
                }
            }
        }
    }
}
