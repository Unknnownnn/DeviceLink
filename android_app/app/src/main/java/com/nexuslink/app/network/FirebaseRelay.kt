package com.nexuslink.app.network

import android.util.Base64
import android.util.Log
import com.google.firebase.database.ChildEventListener
import com.google.firebase.database.DataSnapshot
import com.google.firebase.database.DatabaseError
import com.google.firebase.database.FirebaseDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class FirebaseRelay(
    private val peerFingerprint: String,
    private val scope: CoroutineScope,
    private val onMessageReceived: (String) -> Unit
) {
    private val dbRef = FirebaseDatabase.getInstance("https://devicelink-d4665-default-rtdb.asia-southeast1.firebasedatabase.app/")
        .reference.child("devices").child(peerFingerprint)

    private val aesKey: ByteArray
    private var listener: ChildEventListener? = null

    init {
        val digest = MessageDigest.getInstance("SHA-256")
        aesKey = digest.digest(peerFingerprint.toByteArray(StandardCharsets.UTF_8))
    }

    private fun encrypt(data: ByteArray): String {
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            val nonce = ByteArray(12)
            SecureRandom().nextBytes(nonce)
            val spec = GCMParameterSpec(128, nonce)
            val secretKey = SecretKeySpec(aesKey, "AES")
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, spec)
            val ct = cipher.doFinal(data)
            
            val combined = ByteArray(nonce.size + ct.size)
            System.arraycopy(nonce, 0, combined, 0, nonce.size)
            System.arraycopy(ct, 0, combined, nonce.size, ct.size)
            return Base64.encodeToString(combined, Base64.NO_WRAP)
        } catch (e: Exception) {
            Log.e("FirebaseRelay", "Encrypt failed", e)
            return ""
        }
    }

    private fun decrypt(b64: String): ByteArray? {
        try {
            val combined = Base64.decode(b64, Base64.NO_WRAP)
            val nonce = combined.copyOfRange(0, 12)
            val ct = combined.copyOfRange(12, combined.size)
            
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            val spec = GCMParameterSpec(128, nonce)
            val secretKey = SecretKeySpec(aesKey, "AES")
            cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)
            return cipher.doFinal(ct)
        } catch (e: Exception) {
            Log.e("FirebaseRelay", "Decrypt failed", e)
            return null
        }
    }

    fun startListening() {
        val childListener = object : ChildEventListener {
            override fun onChildAdded(snapshot: DataSnapshot, previousChildName: String?) {
                val b64 = snapshot.getValue(String::class.java)
                if (b64 != null) {
                    scope.launch {
                        val plaintext = decrypt(b64)
                        if (plaintext != null) {
                            val str = String(plaintext, StandardCharsets.UTF_8)
                            onMessageReceived(str)
                        }
                        snapshot.ref.removeValue()
                    }
                }
            }
            override fun onChildChanged(snapshot: DataSnapshot, previousChildName: String?) {}
            override fun onChildRemoved(snapshot: DataSnapshot) {}
            override fun onChildMoved(snapshot: DataSnapshot, previousChildName: String?) {}
            override fun onCancelled(error: DatabaseError) {
                Log.e("FirebaseRelay", "Listen failed: \${error.message}")
            }
        }
        listener = childListener
        dbRef.child("to_phone").addChildEventListener(childListener)
    }

    fun stopListening() {
        listener?.let {
            dbRef.child("to_phone").removeEventListener(it)
        }
        listener = null
    }

    fun sendMessage(data: ByteArray) {
        val b64 = encrypt(data)
        if (b64.isNotEmpty()) {
            dbRef.child("to_pc").push().setValue(b64)
        }
    }
}
