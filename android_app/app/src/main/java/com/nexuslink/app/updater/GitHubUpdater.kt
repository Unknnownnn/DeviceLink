package com.nexuslink.app.updater

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.nexuslink.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

class GitHubUpdater(
    private val context: Context,
    private val githubOwner: String = "Unknnownnn",
    private val githubRepo: String = "DeviceLink",
    private val apkFileName: String = "app-debug.apk",
    private val client: OkHttpClient = OkHttpClient()
) {
    companion object {
        var hasCheckedThisSession = false
        var hasDismissedPopupThisSession = false
    }

    private val _state = MutableStateFlow<UpdaterState>(UpdaterState.Idle)
    val state: StateFlow<UpdaterState> = _state

    fun resetState() {
        _state.value = UpdaterState.Idle
    }

    suspend fun checkForUpdates(force: Boolean = false) {
        if (!force && hasCheckedThisSession) {
            return
        }
        _state.value = UpdaterState.Checking
        val url = "https://api.github.com/repos/$githubOwner/$githubRepo/releases/latest"
        
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(url)
                .header("Accept", "application/vnd.github.v3+json")
                .build()

            try {
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        _state.value = UpdaterState.Error("Server returned code ${response.code}")
                        return@withContext
                    }
                    val body = response.body?.string() ?: ""
                    val json = JSONObject(body)
                    val tagName = json.getString("tag_name")
                    val currentVersion = BuildConfig.VERSION_NAME

                    if (isNewerVersion(currentVersion, tagName)) {
                        // Find apk download url from assets
                        val assets = json.getJSONArray("assets")
                        var apkUrl: String? = null
                        for (i in 0 until assets.length()) {
                            val asset = assets.getJSONObject(i)
                            val name = asset.getString("name")
                            
                            // Prioritize the exact APK name, fallback to any file ending with .apk
                            if (name.equals(apkFileName, ignoreCase = true)) {
                                apkUrl = asset.getString("browser_download_url")
                                break
                            } else if (name.endsWith(".apk", ignoreCase = true)) {
                                apkUrl = asset.getString("browser_download_url")
                            }
                        }

                        if (apkUrl != null) {
                            _state.value = UpdaterState.UpdateAvailable(tagName, apkUrl)
                        } else {
                            _state.value = UpdaterState.Error("No suitable APK file found in the latest release.")
                        }
                    } else {
                        _state.value = UpdaterState.UpToDate
                    }
                }
            } catch (e: Exception) {
                _state.value = UpdaterState.Error(e.message ?: "Failed to check for updates.")
            } finally {
                hasCheckedThisSession = true
            }
        }
    }

    suspend fun downloadAndInstall(downloadUrl: String) {
        _state.value = UpdaterState.Downloading(0.0f)
        val file = File(context.cacheDir, "update.apk")
        if (file.exists()) {
            file.delete()
        }

        val success = withContext(Dispatchers.IO) {
            val request = Request.Builder().url(downloadUrl).build()
            try {
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        _state.value = UpdaterState.Error("Failed to download: code ${response.code}")
                        return@withContext false
                    }
                    val body = response.body ?: throw IOException("Empty response body")
                    val totalBytes = body.contentLength()
                    
                    body.byteStream().use { inputStream ->
                        FileOutputStream(file).use { outputStream ->
                            val buffer = ByteArray(8192)
                            var bytesRead: Int
                            var totalBytesRead = 0L
                            
                            while (inputStream.read(buffer).also { bytesRead = it } != -1) {
                                outputStream.write(buffer, 0, bytesRead)
                                totalBytesRead += bytesRead
                                if (totalBytes > 0) {
                                    val progress = totalBytesRead.toFloat() / totalBytes
                                    _state.value = UpdaterState.Downloading(progress)
                                }
                            }
                        }
                    }
                    true
                }
            } catch (e: Exception) {
                _state.value = UpdaterState.Error(e.message ?: "Failed to download update.")
                false
            }
        }

        if (success) {
            _state.value = UpdaterState.ReadyToInstall
            installApk(file)
        }
    }

    fun installApk(file: File) {
        if (!file.exists()) {
            _state.value = UpdaterState.Error("Installer file not found.")
            return
        }

        // Android 8.0+ requires requesting permission to install unknown apps from this source
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!context.packageManager.canRequestPackageInstalls()) {
                val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES).apply {
                    data = Uri.parse("package:${context.packageName}")
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
                return
            }
        }

        try {
            val apkUri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                file
            )

            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(apkUri, "application/vnd.android.package-archive")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
            }
            context.startActivity(intent)
        } catch (e: Exception) {
            _state.value = UpdaterState.Error("Failed to trigger installation: ${e.message}")
        }
    }

    private fun isNewerVersion(current: String, latest: String): Boolean {
        val cleanCurrent = current.trimStart('v', 'V').split(".")
        val cleanLatest = latest.trimStart('v', 'V').split(".")
        val maxLen = maxOf(cleanCurrent.size, cleanLatest.size)
        for (i in 0 until maxLen) {
            val currVal = cleanCurrent.getOrNull(i)?.toIntOrNull() ?: 0
            val latVal = cleanLatest.getOrNull(i)?.toIntOrNull() ?: 0
            if (latVal > currVal) return true
            if (currVal > latVal) return false
        }
        return false
    }
}
