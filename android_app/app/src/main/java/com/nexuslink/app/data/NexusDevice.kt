package com.nexuslink.app.data

/**
 * Represents a saved or nearby PC in the device list.
 *
 * @param name          Human-readable service name (e.g. "NexusLink._nexuslink._tcp.local.")
 * @param host          Address resolved by NsdManager, or "cloud" when no LAN address was discovered
 * @param port          WebSocket port advertised in the mDNS service record, or 0
 * @param fingerprint   Ed25519 public key fingerprint (hex SHA-256) from TXT record, or null
 *                      if not yet available
 * @param isPaired      Whether this device has a stored trusted peer entry
 * @param isReachable   Whether local discovery or remote presence currently reports the PC
 */
data class NexusDevice(
    val name: String,
    val host: String,
    val port: Int,
    val fingerprint: String? = null,
    val isPaired: Boolean = false,
    val isReachable: Boolean = true,
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
