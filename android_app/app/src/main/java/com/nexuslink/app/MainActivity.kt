package com.nexuslink.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.SystemBarStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nexuslink.app.network.ConnectionManager
import com.nexuslink.app.ui.screens.ConnectionScreen
import com.nexuslink.app.ui.screens.DeviceListScreen
import com.nexuslink.app.ui.screens.QrScannerScreen
import com.nexuslink.app.ui.theme.NexusLinkTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Single-activity host for all NexusLink Compose screens.
 *
 * Navigation graph:
 *   device_list → qr_scanner/{host}/{port}
 *   qr_scanner  → connection/{host}/{port}/{fingerprint}
 *   connection  → (back to device_list)
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var connectionManager: ConnectionManager

    private var shouldRouteToConnected by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        handleIntent(intent)

        // Request core permissions immediately on app launch
        val perms = mutableListOf(
            android.Manifest.permission.READ_PHONE_STATE,
            android.Manifest.permission.READ_CONTACTS,
            android.Manifest.permission.CALL_PHONE,
            android.Manifest.permission.READ_CALL_LOG,
            android.Manifest.permission.READ_SMS,
            android.Manifest.permission.CAMERA
        )
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            perms.add("android.permission.ANSWER_PHONE_CALLS")
        }
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            perms.add(android.Manifest.permission.POST_NOTIFICATIONS)
            perms.add(android.Manifest.permission.READ_MEDIA_IMAGES)
            perms.add(android.Manifest.permission.READ_MEDIA_VIDEO)
        }
        if (android.os.Build.VERSION.SDK_INT <= android.os.Build.VERSION_CODES.S_V2) { // Android 12L and lower
            perms.add(android.Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        if (android.os.Build.VERSION.SDK_INT <= android.os.Build.VERSION_CODES.P) { // Android 9 and lower
            perms.add(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) {
            perms.add("android.permission.BLUETOOTH_CONNECT")
            perms.add("android.permission.BLUETOOTH_SCAN")
        }

        val permissionLauncher = registerForActivityResult(
            androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions()
        ) { }
        permissionLauncher.launch(perms.toTypedArray())

        setContent {
            NexusLinkTheme {
                val navController = rememberNavController()
                NexusLinkNavGraph(
                    navController = navController,
                    connectionManager = connectionManager,
                    shouldRouteToConnected = shouldRouteToConnected,
                    onRouteHandled = { shouldRouteToConnected = false }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.getBooleanExtra("route_to_connected", false) == true) {
            shouldRouteToConnected = true
        }
    }
}

// ── Navigation Graph ──────────────────────────────────────────────────────────

object Routes {
    const val DEVICE_LIST = "device_list"
    const val QR_SCANNER  = "qr_scanner?host={host}&port={port}"
    const val CONNECTION  = "connection/{host}/{port}/{fingerprint}"
    const val SETTINGS    = "settings"

    fun qrScanner(host: String? = null, port: Int? = null): String {
        return if (host != null && port != null) "qr_scanner?host=$host&port=$port"
        else "qr_scanner"
    }
    fun connection(host: String, port: Int, fingerprint: String) = "connection/$host/$port/$fingerprint"
}

@Composable
fun NexusLinkNavGraph(
    navController: NavHostController,
    connectionManager: ConnectionManager,
    shouldRouteToConnected: Boolean,
    onRouteHandled: () -> Unit
) {
    val uiState by connectionManager.uiState.collectAsState()

    LaunchedEffect(shouldRouteToConnected) {
        if (shouldRouteToConnected) {
            val host = uiState.host
            val port = uiState.port
            val fingerprint = uiState.peerFingerprint
            if (host.isNotEmpty() && port != 0 && !fingerprint.isNullOrEmpty()) {
                navController.navigate(Routes.connection(host, port, fingerprint)) {
                    launchSingleTop = true
                }
            }
            onRouteHandled()
        }
    }

    NavHost(
        navController = navController,
        startDestination = Routes.DEVICE_LIST,
    ) {
        composable(Routes.DEVICE_LIST) {
            DeviceListScreen(
                onDeviceSelected = { host, port, isPaired, fingerprint ->
                    if (isPaired && fingerprint != null) {
                        navController.navigate(Routes.connection(host, port, fingerprint))
                    } else {
                        navController.navigate(Routes.qrScanner(host, port))
                    }
                },
                onManualScan = {
                    navController.navigate(Routes.qrScanner())
                },
                onSettingsClicked = {
                    navController.navigate(Routes.SETTINGS)
                }
            )
        }

        composable(Routes.SETTINGS) {
            com.nexuslink.app.ui.screens.SettingsScreen(
                onBack = { navController.popBackStack() }
            )
        }

        composable(
            route = Routes.QR_SCANNER,
            arguments = listOf(
                androidx.navigation.navArgument("host") { nullable = true },
                androidx.navigation.navArgument("port") { nullable = true; type = androidx.navigation.NavType.StringType }
            )
        ) { backStack ->
            val host = backStack.arguments?.getString("host")
            val port = backStack.arguments?.getString("port")?.toIntOrNull()
            QrScannerScreen(
                targetHost = host,
                targetPort = port,
                onPairingComplete = { scannedHost, scannedPort, fingerprint ->
                    navController.navigate(Routes.connection(scannedHost, scannedPort, fingerprint)) {
                        popUpTo(Routes.DEVICE_LIST)
                    }
                }
            )
        }

        composable(Routes.CONNECTION) { backStack ->
            val host = backStack.arguments?.getString("host") ?: ""
            val port = backStack.arguments?.getString("port")?.toIntOrNull() ?: 47200
            val fingerprint = backStack.arguments?.getString("fingerprint") ?: ""
            ConnectionScreen(
                host = host,
                port = port,
                fingerprint = fingerprint,
                onDisconnect = {
                    navController.navigate(Routes.DEVICE_LIST) {
                        popUpTo(Routes.DEVICE_LIST) { inclusive = true }
                    }
                }
            )
        }
    }
}
