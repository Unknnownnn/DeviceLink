package com.nexuslink.app.ui.screens

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
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
    var isAiExpanded by remember { mutableStateOf(false) }

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
                            iconTint = Violet400,
                            title = "Handshaking...",
                            subtitle = "Performing X25519 ECDH key exchange",
                            containerColor = Surface800
                        )
                    }
                    is ConnectionState.Connected -> {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier.verticalScroll(rememberScrollState())
                        ) {
                            StatusBanner(
                                icon = Icons.Default.CheckCircle,
                                iconTint = Emerald400,
                                title = "Secure Channel Active",
                                subtitle = "Encrypted via ChaCha20-Poly1305",
                                containerColor = Emerald400.copy(alpha = 0.1f),
                                borderColor = Emerald400.copy(alpha = 0.3f)
                            )
                            
                            Spacer(modifier = Modifier.height(32.dp))
                            
                            // Metrics Card
                            Card(
                                colors = CardDefaults.cardColors(containerColor = Surface800),
                                shape = RoundedCornerShape(16.dp),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(modifier = Modifier.padding(16.dp)) {
                                    Text(
                                        text = "E2E Encryption Test",
                                        style = MaterialTheme.typography.titleMedium,
                                        color = Violet200
                                    )
                                    Spacer(modifier = Modifier.height(16.dp))
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween
                                    ) {
                                        Metric(label = "Pings Sent", value = uiState.pingCount.toString())
                                        Metric(label = "Pongs Received", value = uiState.pongCount.toString())
                                    }
                                    if (uiState.lastPongPayload.isNotBlank()) {
                                        Spacer(modifier = Modifier.height(16.dp))
                                        Text(
                                            text = "Last payload: ${uiState.lastPongPayload}",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = OnSurfaceDim,
                                            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                                        )
                                    }
                                    Spacer(modifier = Modifier.height(24.dp))
                                    Button(
                                        onClick = { viewModel.sendPing() },
                                        modifier = Modifier.fillMaxWidth(),
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = Violet500,
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("Send Secure Ping")
                                    }
                                    
                                    Spacer(modifier = Modifier.height(12.dp))
                                    
                                    Button(
                                        onClick = { viewModel.pushClipboardToPc() },
                                        modifier = Modifier.fillMaxWidth(),
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = Cyan500,
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("Push Phone Clipboard to PC")
                                    }

                                    Spacer(modifier = Modifier.height(12.dp))

                                    Button(
                                        onClick = { filePickerLauncher.launch("*/*") },
                                        modifier = Modifier.fillMaxWidth(),
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = Violet400,
                                            contentColor = Color.White
                                        )
                                    ) {
                                        Text("Send File to PC")
                                    }
                                    
                                    if (uiState.lastClipboardSync.isNotBlank()) {
                                        Spacer(modifier = Modifier.height(16.dp))
                                        Text("Last Synced Clipboard:", color = OnSurfaceDim, style = MaterialTheme.typography.bodySmall)
                                        Text(uiState.lastClipboardSync, color = OnSurface, maxLines = 1)
                                    }

                                    Spacer(modifier = Modifier.height(24.dp))
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clickable { isAiExpanded = !isAiExpanded }
                                            .padding(vertical = 8.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text("AI Orchestrator", color = Cyan400, style = MaterialTheme.typography.titleMedium)
                                        Icon(
                                            if (isAiExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                                            contentDescription = "Expand AI",
                                            tint = Cyan400
                                        )
                                    }
                                    
                                    androidx.compose.animation.AnimatedVisibility(visible = isAiExpanded) {
                                        Column(modifier = Modifier.fillMaxWidth()) {
                                            Spacer(modifier = Modifier.height(8.dp))
                                            OutlinedTextField(
                                                value = nlpPrompt,
                                                onValueChange = { nlpPrompt = it },
                                                label = { Text("Enter natural language command") },
                                                modifier = Modifier.fillMaxWidth(),
                                                colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                                    focusedBorderColor = Cyan400,
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
                                                colors = ButtonDefaults.buttonColors(containerColor = Cyan500)
                                            ) {
                                                Text("Execute AI Command")
                                            }
                                        }
                                    }
                                    
                                    Spacer(modifier = Modifier.height(32.dp))
                                    Text("App Launcher Deck", color = Emerald400, style = MaterialTheme.typography.titleMedium)
                                    Spacer(modifier = Modifier.height(16.dp))
                                    
                                    // Row 1: Apps
                                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                        DeckButton("Notepad", Icons.Default.Apps, Emerald500) { viewModel.launchApp("notepad") }
                                        DeckButton("Calculator", Icons.Default.Apps, Emerald500) { viewModel.launchApp("calculator") }
                                        DeckButton("Steam", Icons.Default.PlayArrow, Emerald500) { viewModel.launchApp("cs2") }
                                    }
                                    
                                    Spacer(modifier = Modifier.height(32.dp))
                                    Text("Power Controls", color = Rose400, style = MaterialTheme.typography.titleMedium)
                                    Spacer(modifier = Modifier.height(16.dp))
                                    
                                    // Row 2: Power
                                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                                        DeckButton("Lock", Icons.Default.Lock, Violet500) { viewModel.sendPowerCommand("lock") }
                                        DeckButton("Sleep", Icons.Default.NightsStay, Violet500) { viewModel.sendPowerCommand("sleep") }
                                        DeckButton("Shutdown", Icons.Default.PowerSettingsNew, Rose500) { viewModel.sendPowerCommand("shutdown") }
                                    }
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
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { nlpResponseDialogText = null },
            title = { Text("AI Execution Result") },
            text = { Text(nlpResponseDialogText ?: "") },
            confirmButton = {
                androidx.compose.material3.TextButton(onClick = { nlpResponseDialogText = null }) {
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
