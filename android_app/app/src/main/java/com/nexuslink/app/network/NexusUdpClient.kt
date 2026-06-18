package com.nexuslink.app.network

import android.util.Log
import com.nexuslink.app.data.IdentityManager
import com.nexuslink.app.data.decodeB64Url
import com.nexuslink.app.data.encodeB64Url
import com.nexuslink.app.network.crypto.HandshakeManager
import com.nexuslink.app.network.crypto.SessionCipher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.security.SecureRandom
import java.util.UUID

private const val TAG = "NexusUdpClient"

class NexusUdpClient(
    private val identity: IdentityManager,
    private val peerFingerprint: String,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.IO)
) {
    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = _state

    val events = Channel<SessionEvent>(Channel.BUFFERED)

    private var socket: DatagramSocket? = null
    private var cipher: SessionCipher? = null
    private val handshake = HandshakeManager()
    
    private var activePeerAddress: InetSocketAddress? = null
    
    private var isRunning = false
    private var handshakeJob: kotlinx.coroutines.Job? = null
    
    private var peerX25519B64: String? = null
    private var peerEd25519B64: String? = null

    private var receivedHolePunch = false
    private var receivedHolePunchAck = false
    
    private val stunTxId = ByteArray(12)
    private var stunResult: InetSocketAddress? = null
    private val stunLock = Any()

    fun getLocalIp(): String {
        return try {
            val dummy = DatagramSocket()
            dummy.connect(InetAddress.getByName("8.8.8.8"), 80)
            val ip = dummy.localAddress.hostAddress
            dummy.close()
            ip
        } catch (e: Exception) {
            "127.0.0.1"
        }
    }

    suspend fun queryStun(localPort: Int): InetSocketAddress? {
        if (socket == null) {
            try {
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    bind(InetSocketAddress(localPort))
                    soTimeout = 0
                }
                isRunning = true
                startListening(socket!!)
            } catch (e: Exception) {
                Log.e(TAG, "STUN: Failed to create/bind socket on port $localPort: ${e.message}", e)
                return null
            }
        }
        val sock = socket ?: return null
        Log.i(TAG, "STUN: queryStun starting on local port ${sock.localPort}")

        try {
            SecureRandom().nextBytes(stunTxId)
            
            val buffer = ByteBuffer.allocate(20)
            buffer.putShort(0x0001.toShort()) // type
            buffer.putShort(0x0000.toShort()) // length
            buffer.putInt(0x2112A442.toInt()) // magic cookie
            buffer.put(stunTxId)
            
            val payload = buffer.array()
            
            val stunServers = listOf(
                Pair("173.194.202.127", 19302),
                Pair("74.125.143.127", 19302),
                Pair("108.177.119.127", 19302),
                Pair("54.172.47.199", 3478),
                Pair("stun.l.google.com", 19302),
                Pair("stun1.l.google.com", 19302),
                Pair("stun.chat.twilio.com", 3478),
                Pair("stun.sipgate.net", 10000)
            )
            
            synchronized(stunLock) {
                stunResult = null
            }
            
            for (attempt in 0 until 2) {
                Log.i(TAG, "STUN: Sending query attempt $attempt...")
                for (server in stunServers) {
                    scope.launch(Dispatchers.IO) {
                        try {
                            // If the server string is already an IP, getByName returns it instantly
                            val addresses = InetAddress.getAllByName(server.first)
                            val ip = addresses.firstOrNull { it is java.net.Inet4Address }
                            if (ip == null) {
                                Log.w(TAG, "STUN: No IPv4 address found for ${server.first}")
                                return@launch
                            }
                            Log.i(TAG, "STUN: Resolved ${server.first} to IPv4 $ip, sending packet...")
                            val packet = DatagramPacket(payload, payload.size, ip, server.second)
                            sock.send(packet)
                        } catch (e: Exception) {
                            Log.w(TAG, "STUN: Failed to send request to ${server.first}: ${e.message}")
                        }
                    }
                }
                delay(1200)
                synchronized(stunLock) {
                    if (stunResult != null) {
                        return@queryStun stunResult
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "STUN query error: ${e.message}")
        }
        Log.w(TAG, "STUN: Query finished without results.")
        return null
    }

    fun parseStunResponse(data: ByteArray, length: Int) {
        try {
            val resp = ByteBuffer.wrap(data, 0, length)
            if (resp.remaining() < 20) {
                Log.w(TAG, "STUN Parse: Packet too short (${resp.remaining()})")
                return
            }
            
            val msgType = resp.short
            val msgLen = resp.short
            val magic = resp.int
            val rxTxId = ByteArray(12)
            resp.get(rxTxId)
            
            Log.d(TAG, "STUN Parse: msgType=0x${Integer.toHexString(msgType.toInt() and 0xFFFF)}, magic=0x${Integer.toHexString(magic)}")
            
            if (msgType != 0x0101.toShort()) {
                Log.w(TAG, "STUN Parse: Unexpected message type 0x${Integer.toHexString(msgType.toInt() and 0xFFFF)}")
                return
            }
            if (!rxTxId.contentEquals(stunTxId)) {
                Log.w(TAG, "STUN Parse: Transaction ID mismatch")
                return
            }
            
            var pos = 20
            while (pos + 4 <= length) {
                resp.position(pos)
                val attrType = resp.short.toInt() and 0xFFFF
                val attrLen = resp.short.toInt() and 0xFFFF
                pos += 4
                if (pos + attrLen > length) {
                    Log.w(TAG, "STUN Parse: Attribute length overflow")
                    break
                }
                
                if (attrType == 0x0001) { // MAPPED-ADDRESS
                    resp.position(pos)
                    val unused = resp.get()
                    val family = resp.get().toInt()
                    val port = resp.short.toInt() and 0xFFFF
                    if (family == 1) { // IPv4
                        val ipBytes = ByteArray(4)
                        resp.get(ipBytes)
                        val ip = InetAddress.getByAddress(ipBytes).hostAddress
                        synchronized(stunLock) {
                            stunResult = InetSocketAddress(ip, port)
                        }
                        Log.i(TAG, "STUN Parse: Decoded MAPPED-ADDRESS: $ip:$port")
                        return
                    }
                } else if (attrType == 0x0020 || attrType == 0x8020) { // XOR-MAPPED-ADDRESS
                    resp.position(pos)
                    val unused = resp.get()
                    val family = resp.get().toInt()
                    val xPort = resp.short.toInt() and 0xFFFF
                    val port = xPort xor 0x2112
                    if (family == 1) { // IPv4
                        val xIp = resp.int
                        val ipInt = xIp xor 0x2112A442.toInt()
                        val ipBytes = ByteBuffer.allocate(4).putInt(ipInt).array()
                        val ip = InetAddress.getByAddress(ipBytes).hostAddress
                        synchronized(stunLock) {
                            stunResult = InetSocketAddress(ip, port)
                        }
                        Log.i(TAG, "STUN Parse: Decoded XOR-MAPPED-ADDRESS: $ip:$port")
                        return
                    }
                }
                pos += (attrLen + 3) and 3.inv()
            }
        } catch (e: Exception) {
            Log.e(TAG, "STUN parse error: ${e.message}")
        }
    }

    fun startListening(sock: DatagramSocket) {
        scope.launch(Dispatchers.IO) {
            val buf = ByteArray(65535)
            while (isRunning) {
                try {
                    val packet = DatagramPacket(buf, buf.size)
                    sock.receive(packet)
                    val len = packet.length
                    val addr = packet.socketAddress as InetSocketAddress
                    val data = packet.data.copyOfRange(0, len)
                    
                    if (len >= 20 && ByteBuffer.wrap(data, 4, 4).int == 0x2112A442.toInt()) {
                        parseStunResponse(data, len)
                        continue
                    }
                    
                    if (data.contentEquals("HOLE_PUNCH".toByteArray(Charsets.UTF_8))) {
                        Log.i(TAG, "Received HOLE_PUNCH from $addr")
                        sock.send(DatagramPacket("HOLE_PUNCH_ACK".toByteArray(Charsets.UTF_8), 14, addr))
                        receivedHolePunch = true
                        if (activePeerAddress == null) {
                            activePeerAddress = addr
                            Log.i(TAG, "Hole punch active address resolved: $addr")
                        }
                        continue
                    }
                    
                    if (data.contentEquals("HOLE_PUNCH_ACK".toByteArray(Charsets.UTF_8))) {
                        Log.i(TAG, "Received HOLE_PUNCH_ACK from $addr")
                        receivedHolePunchAck = true
                        if (activePeerAddress == null) {
                            activePeerAddress = addr
                            Log.i(TAG, "Hole punch active address resolved: $addr")
                        }
                        continue
                    }
                    
                    val c = cipher
                    if (c == null) {
                        try {
                            val str = String(data, Charsets.UTF_8)
                            val json = JSONObject(str)
                            val type = json.optString("type")
                            if (type == "HELLO_ACK") {
                                Log.i(TAG, "Received HELLO_ACK via UDP from $addr")
                                activePeerAddress = addr
                                processHelloAck(json)
                            }
                        } catch (e: Exception) {
                            // ignore
                        }
                        continue
                    }
                    
                    try {
                        val plain = c.decrypt(data)
                        val json = JSONObject(String(plain, Charsets.UTF_8))
                        val type = json.optString("type")
                        val payload = json.optJSONObject("payload") ?: JSONObject()
                        
                        if (type == "CLIPBOARD_UPDATE") {
                            val text = payload.optString("text", "")
                            scope.launch { events.send(SessionEvent.ClipboardUpdate(text)) }
                        } else {
                            Log.d(TAG, "UDP incoming message: $type")
                            scope.launch { events.send(SessionEvent.MessageReceived(type, payload)) }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "Failed to decrypt UDP packet from $addr: ${e.message}")
                    }
                    
                } catch (e: Exception) {
                    if (isRunning) {
                        delay(100)
                    }
                }
            }
        }
    }

    fun startHolePunchingLoop(localIp: String, localPort: Int, publicIp: String, publicPort: Int, peerCandidates: JSONObject) {
        isRunning = true
        if (socket == null) {
            try {
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    bind(InetSocketAddress(localPort))
                    soTimeout = 0
                }
                startListening(socket!!)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to bind DatagramSocket in startHolePunchingLoop: ${e.message}", e)
                _state.value = ConnectionState.Error("Bind error: ${e.message}")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Bind error: ${e.message}")) }
                return
            }
        }
        
        handshakeJob = scope.launch(Dispatchers.IO) {
            _state.value = ConnectionState.Connecting
            
            val destinations = mutableListOf<InetSocketAddress>()
            val pLocalIp = peerCandidates.optString("local_ip")
            val pLocalPort = peerCandidates.optInt("local_port", 0)
            val pPublicIp = peerCandidates.optString("public_ip")
            val pPublicPort = peerCandidates.optInt("public_port", 0)
            
            if (pLocalIp.isNotBlank() && pLocalPort > 0) {
                destinations.add(InetSocketAddress(pLocalIp, pLocalPort))
            }
            if (pPublicIp.isNotBlank() && pPublicPort > 0) {
                destinations.add(InetSocketAddress(pPublicIp, pPublicPort))
            }
            
            Log.i(TAG, "Starting hole punch packets towards: $destinations")
            
            var attempts = 0
            while (isRunning && activePeerAddress == null && attempts < 30) {
                for (dest in destinations) {
                    try {
                        val data = "HOLE_PUNCH".toByteArray(Charsets.UTF_8)
                        socket?.send(DatagramPacket(data, data.size, dest))
                    } catch (e: Exception) {
                        // ignore
                    }
                }
                attempts++
                delay(200)
            }
            
            if (activePeerAddress == null) {
                Log.w(TAG, "Hole punch failed (no response received from PC)")
                _state.value = ConnectionState.Error("Hole punch timeout")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Hole punch timeout")) }
                return@launch
            }
            
            _state.value = ConnectionState.Handshaking
            runHandshakeLoop()
        }
    }

    private suspend fun runHandshakeLoop() {
        val dest = activePeerAddress ?: return
        val sock = socket ?: return
        
        Log.i(TAG, "UDP hole punched! Running cryptographic handshake with $dest")
        
        val hello = JSONObject().apply {
            put("type", "HELLO")
            put("id", UUID.randomUUID().toString())
            put("payload", JSONObject().apply {
                put("x25519_public_key", handshake.publicKeyB64)
                put("ed25519_public_key", identity.publicKeyB64)
                put("device_name", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            })
        }
        val helloBytes = hello.toString().toByteArray(Charsets.UTF_8)
        
        var attempts = 0
        while (isRunning && peerX25519B64 == null && attempts < 10) {
            try {
                sock.send(DatagramPacket(helloBytes, helloBytes.size, dest))
                Log.d(TAG, "Sent HELLO to $dest (attempt ${attempts + 1})")
            } catch (e: Exception) {
                // ignore
            }
            attempts++
            delay(1000)
        }
        
        if (peerX25519B64 == null) {
            Log.w(TAG, "UDP Handshake failed waiting for HELLO_ACK")
            _state.value = ConnectionState.Error("Handshake timed out")
            scope.launch { events.send(SessionEvent.HandshakeFailed("Handshake timed out")) }
            return
        }
        
        val pcX25519Raw = decodeB64Url(peerX25519B64!!)
        val myTranscript = handshake.publicKeyBytes + pcX25519Raw
        val mySignature = identity.sign(myTranscript)
        val mySignatureB64 = encodeB64Url(mySignature)
        
        val confirm = JSONObject().apply {
            put("type", "HELLO_CONFIRM")
            put("id", UUID.randomUUID().toString())
            put("payload", JSONObject().apply {
                put("signature", mySignatureB64)
            })
        }
        val confirmBytes = confirm.toString().toByteArray(Charsets.UTF_8)
        
        for (i in 0 until 3) {
            try {
                sock.send(DatagramPacket(confirmBytes, confirmBytes.size, dest))
                Log.d(TAG, "Sent HELLO_CONFIRM to $dest (retry ${i + 1})")
            } catch (e: Exception) {
                // ignore
            }
            delay(300)
        }
        
        Log.i(TAG, "UDP Handshake successful! Secure session active.")
        _state.value = ConnectionState.Connected(dest.hostString, dest.port)
        scope.launch { events.send(SessionEvent.SessionEstablished(peerEd25519B64!!, "UDP: ${dest.hostString}")) }
    }

    private fun processHelloAck(json: JSONObject) {
        try {
            val payload = json.getJSONObject("payload")
            val pcX25519B64 = payload.getString("x25519_public_key")
            val pcEd25519B64 = payload.getString("ed25519_public_key")
            val signatureB64 = payload.getString("signature")

            val pcX25519Raw = decodeB64Url(pcX25519B64)
            val transcript = pcX25519Raw + handshake.publicKeyBytes

            val pcEd25519Raw = decodeB64Url(pcEd25519B64)
            val actualFp = java.security.MessageDigest.getInstance("SHA-256")
                .digest(pcEd25519Raw)
                .joinToString("") { "%02x".format(it) }

            if (actualFp != peerFingerprint) {
                Log.e(TAG, "HELLO_ACK fingerprint mismatch! Expected $peerFingerprint, got $actualFp")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Key fingerprint mismatch")) }
                return
            }

            val sigRaw = decodeB64Url(signatureB64)
            val verified = identity.verify(pcEd25519B64, transcript, sigRaw)

            if (!verified) {
                Log.e(TAG, "HELLO_ACK signature verification FAILED")
                scope.launch { events.send(SessionEvent.HandshakeFailed("Signature verification failed")) }
                return
            }

            peerX25519B64 = pcX25519B64
            peerEd25519B64 = pcEd25519B64
            
            val sessionKey = handshake.deriveSessionKey(pcX25519B64)
            cipher = SessionCipher(sessionKey)
            
        } catch (e: Exception) {
            Log.e(TAG, "processHelloAck error: ${e.message}", e)
        }
    }

    fun send(type: String, payload: JSONObject = JSONObject()) {
        val c = cipher ?: return
        val dest = activePeerAddress ?: return
        val sock = socket ?: return
        
        try {
            val msg = JSONObject().apply {
                put("type", type)
                put("id", UUID.randomUUID().toString())
                put("payload", payload)
            }
            val frame = c.encrypt(msg.toString().toByteArray(Charsets.UTF_8))
            val packet = DatagramPacket(frame, frame.size, dest)
            scope.launch(Dispatchers.IO) {
                try {
                    sock.send(packet)
                    Log.d(TAG, "Sent UDP packet type: $type to $dest")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to send packet over UDP: ${e.message}")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "UDP encrypt send failed: ${e.message}")
        }
    }

    fun disconnect() {
        isRunning = false
        handshakeJob?.cancel()
        socket?.close()
        socket = null
        cipher = null
        activePeerAddress = null
    }
}
