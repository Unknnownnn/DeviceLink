package com.nexuslink.app.ui.theme

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color

private val NexusDarkColorScheme = darkColorScheme(
    primary          = Blue400,
    onPrimary        = Color.White,
    primaryContainer = Surface800,
    onPrimaryContainer = Blue200,

    secondary        = Cyan400,
    onSecondary      = Surface900,
    secondaryContainer = Surface700,
    onSecondaryContainer = Cyan200,

    tertiary         = Emerald400,
    onTertiary       = Surface900,

    background       = Surface900,
    onBackground     = OnSurface,

    surface          = Surface800,
    onSurface        = OnSurface,
    surfaceVariant   = Surface700,
    onSurfaceVariant = OnSurfaceDim,

    error            = Rose500,
    onError          = Surface900,
    errorContainer   = Rose500.copy(alpha = 0.2f),
    onErrorContainer = Rose400,

    outline          = Blue300.copy(alpha = 0.3f),
    outlineVariant   = Surface600,
)

@Composable
fun NexusLinkTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NexusDarkColorScheme,
        typography = NexusTypography,
    ) {
        // Surface fills the entire screen including behind status/nav bars so
        // enableEdgeToEdge() doesn't leave black bars at top and bottom.
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background
        ) {
            content()
        }
    }
}
