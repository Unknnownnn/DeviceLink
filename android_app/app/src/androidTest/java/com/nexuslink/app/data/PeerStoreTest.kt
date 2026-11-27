package com.nexuslink.app.data

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PeerStoreTest {
    private val app = ApplicationProvider.getApplicationContext<Context>()
    private val directory = Files.createTempDirectory(app.cacheDir.toPath(), "peer-store-test").toFile()
    private val context = object : ContextWrapper(app) {
        override fun getFilesDir() = directory
    }
    private val fingerprint = "a".repeat(64)
    private val endpoint = LanEndpoint("192.168.1.20", 47200)

    @After
    fun cleanUp() {
        directory.deleteRecursively()
    }

    @Test
    fun pairingSurvivesRestartBeforeAnyDirectHandshake() {
        PeerStore(context).rememberPairing(fingerprint, endpoint)

        val reloaded = PeerStore(context).getPeer(fingerprint)

        assertEquals(TrustedPeer(fingerprint, displayName = endpoint.host, lanEndpoint = endpoint), reloaded)
    }

    @Test
    fun legacyPeerCanBeUpdatedAndUdpConfirmationPreservesItsLanAddress() {
        File(directory, "trusted_peers.json").writeText(
            """{"$fingerprint":{"ed25519_pub":"existing-key","name":"Office PC"}}""",
        )
        val store = PeerStore(context)
        assertEquals(TrustedPeer(fingerprint, "existing-key", "Office PC"), store.getPeer(fingerprint))

        store.confirmPeer(fingerprint, "existing-key", lanEndpoint = endpoint)
        store.confirmPeer(fingerprint, "existing-key")

        assertEquals(
            TrustedPeer(fingerprint, "existing-key", "Office PC", endpoint),
            PeerStore(context).getPeer(fingerprint),
        )
    }

    @Test
    fun lateHandshakeDoesNotRestoreForgottenPeer() {
        val store = PeerStore(context)
        store.rememberPairing(fingerprint, endpoint)
        store.removePeer(fingerprint)
        store.confirmPeer(fingerprint, "pc-key", "Office PC", endpoint)

        assertNull(PeerStore(context).getPeer(fingerprint))
    }
}
