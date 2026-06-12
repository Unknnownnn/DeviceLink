package com.nexuslink.app.data

/**
 * Represents a NexusLink-capable PC discovered on the local network via mDNS.
 *
 * @param name          Human-readable service name (e.g. "NexusLink._nexuslink._tcp.local.")
 * @param host          IP address or hostname resolved by NsdManager
 * @param port          WebSocket port advertised in the mDNS service record
 * @param fingerprint   Ed25519 public key fingerprint (hex SHA-256) from TXT record, or null
 *                      if not yet available
 * @param isPaired      Whether this device has a stored trusted peer entry
 */
data class NexusDevice(
    val name: String,
    val host: String,
    val port: Int,
    val fingerprint: String? = null,
    val isPaired: Boolean = false,
) {
    /** Display-friendly device name stripped of mDNS suffixes. */
    val displayName: String
        get() = name
            .removePrefix("DeviceLink_")
            .removeSuffix("._devicelink._tcp.local.")
            .removeSuffix("._devicelink._tcp.local")
            .removeSuffix("._nexuslink._tcp.local.")
            .removeSuffix("._nexuslink._tcp.local")
            .ifBlank { host }
}
