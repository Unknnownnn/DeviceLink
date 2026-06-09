package com.nexuslink.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val NexusDarkColorScheme = darkColorScheme(
    primary          = Violet400,
    onPrimary        = Surface900,
    primaryContainer = Indigo800,
    onPrimaryContainer = Violet200,

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

    outline          = Violet300.copy(alpha = 0.3f),
    outlineVariant   = Surface600,
)

@Composable
fun NexusLinkTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NexusDarkColorScheme,
        typography = NexusTypography,
        content = content,
    )
}
