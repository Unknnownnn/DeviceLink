package com.nexuslink.app.ui.viewmodels

import com.nexuslink.app.data.NexusDevice
import com.nexuslink.app.data.TrustedPeer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DiscoveryDeviceListTest {
    private val peer = TrustedPeer(fingerprint = "a".repeat(64), displayName = "Office PC")
    private val now = 1_000_000L

    @Test
    fun savedPcCanBeSelectedWithoutLocalDiscoveryOrCloudPresence() {
        val device = buildDeviceList(emptyList(), mapOf(peer.fingerprint to peer), emptyMap(), now).single()

        assertEquals(peer.fingerprint, device.fingerprint)
        assertEquals(peer.displayName, device.displayName)
        assertEquals("cloud", device.host)
        assertEquals(0, device.port)
        assertTrue(device.isPaired)
        assertFalse(device.isReachable)
    }

    @Test
    fun matchingMdnsAddressTakesPrecedenceOverTheSavedCard() {
        val local = NexusDevice("Office PC", "192.168.1.20", 47200, peer.fingerprint)
        val unpaired = NexusDevice("Other PC", "192.168.1.21", 47200, "b".repeat(64))

        val devices = buildDeviceList(
            listOf(local, unpaired), mapOf(peer.fingerprint to peer), mapOf(peer.fingerprint to now), now,
        )

        assertEquals(listOf(local.copy(isPaired = true), unpaired), devices)
    }

    @Test
    fun cloudPresenceExpiresWithoutRemovingTheSavedPc() {
        val peers = mapOf(peer.fingerprint to peer)
        val online = buildDeviceList(emptyList(), peers, mapOf(peer.fingerprint to now), now).single()
        val stale = buildDeviceList(emptyList(), peers, mapOf(peer.fingerprint to now), now + 600_001).single()

        assertTrue(online.isReachable)
        assertEquals(online.copy(isReachable = false), stale)
    }
}
