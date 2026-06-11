package com.nexuslink.app.updater

sealed class UpdaterState {
    object Idle : UpdaterState()
    object Checking : UpdaterState()
    data class UpdateAvailable(val latestVersion: String, val downloadUrl: String) : UpdaterState()
    data class Downloading(val progress: Float) : UpdaterState() // progress from 0.0f to 1.0f
    object ReadyToInstall : UpdaterState()
    object UpToDate : UpdaterState()
    data class Error(val message: String) : UpdaterState()
}
