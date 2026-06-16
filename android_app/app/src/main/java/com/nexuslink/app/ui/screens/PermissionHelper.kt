package com.nexuslink.app.ui.screens

import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.os.Process

/**
 * Checks if the MIUI custom permission "Display pop-up windows while running in the background" is granted.
 * The operation code is 10021 (OP_BACKGROUND_START_ACTIVITY).
 */
fun isMiuiBackgroundStartActivityAllowed(context: Context): Boolean {
    return try {
        val mgr = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val m = AppOpsManager::class.java.getMethod(
            "checkOpNoThrow",
            Int::class.javaPrimitiveType,
            Int::class.javaPrimitiveType,
            String::class.java
        )
        val result = m.invoke(
            mgr,
            10021, // OP_BACKGROUND_START_ACTIVITY (run new windows while running in background)
            Process.myUid(),
            context.packageName
        ) as Int
        result == AppOpsManager.MODE_ALLOWED
    } catch (e: Exception) {
        // Fallback to true if reflection fails or if it's not a MIUI device
        true
    }
}

/**
 * Checks if the device is a MIUI/HyperOS device by testing if the permission editor activity is queryable.
 */
fun checkIsMiuiDevice(context: Context): Boolean {
    return try {
        val intent = Intent("miui.intent.action.APP_PERM_EDITOR").apply {
            setClassName("com.miui.securitycenter", "com.miui.permcenter.permissions.PermissionsEditorActivity")
            putExtra("extra_pkgname", context.packageName)
        }
        context.packageManager.queryIntentActivities(intent, 0).isNotEmpty()
    } catch (e: Exception) {
        false
    }
}

/**
 * Intent helper to launch MIUI APP_PERM_EDITOR or fall back to standard details settings.
 */
fun openMiuiPermissionSettings(context: Context) {
    try {
        val intent = Intent("miui.intent.action.APP_PERM_EDITOR").apply {
            setClassName("com.miui.securitycenter", "com.miui.permcenter.permissions.PermissionsEditorActivity")
            putExtra("extra_pkgname", context.packageName)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    } catch (e: Exception) {
        try {
            val intent = Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = android.net.Uri.fromParts("package", context.packageName, null)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        } catch (ex: Exception) {
            // No-op fallback
        }
    }
}
