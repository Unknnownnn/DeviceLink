package com.nexuslink.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nexuslink.app.ui.screens.ConnectionScreen
import com.nexuslink.app.ui.screens.DeviceListScreen
import com.nexuslink.app.ui.screens.QrScannerScreen
import com.nexuslink.app.ui.theme.NexusLinkTheme
import dagger.hilt.android.AndroidEntryPoint

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

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
        }
        if (android.os.Build.VERSION.SDK_INT <= android.os.Build.VERSION_CODES.S_V2) { // Android 12L and lower
            perms.add(android.Manifest.permission.READ_EXTERNAL_STORAGE)
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
                NexusLinkNavGraph(navController)
            }
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
fun NexusLinkNavGraph(navController: NavHostController) {
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
