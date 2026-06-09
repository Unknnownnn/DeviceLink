package com.nexuslink.app

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application class required by Hilt for dependency injection.
 * Declared in AndroidManifest.xml as android:name=".NexusLinkApplication".
 */
@HiltAndroidApp
class NexusLinkApplication : Application()
