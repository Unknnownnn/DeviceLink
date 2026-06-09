package com.nexuslink.app.network

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.core.app.NotificationCompat
import android.util.Base64
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.OutputStream
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "FileTransferManager"
private const val CHUNK_SIZE = 64 * 1024 // 64 KB

@Singleton
class FileTransferManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val connectionManager: ConnectionManager
) {
    private val scope = CoroutineScope(Dispatchers.IO)

    private data class TransferState(
        val stream: OutputStream,
        val fileName: String,
        val fileSize: Long,
        var bytesReceived: Long,
        val notificationId: Int
    )

    private val activeReceives = mutableMapOf<String, TransferState>()
    private val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    init {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "nexus_file_transfer",
                "File Transfers",
                NotificationManager.IMPORTANCE_LOW
            )
            notificationManager.createNotificationChannel(channel)
        }
        scope.launch {
            connectionManager.fileEvents.collect { event ->
                when (event.type) {
                    "file_transfer_start" -> handleTransferStart(event.payload)
                    "file_chunk" -> handleFileChunk(event.payload)
                    "file_transfer_complete" -> handleTransferComplete(event.payload)
                }
            }
        }
    }

    private fun handleTransferStart(payload: JSONObject) {
        val fileId = payload.optString("file_id")
        var fileName = payload.optString("file_name")
        val fileSize = payload.optLong("file_size", 0L)
        if (fileId.isBlank() || fileName.isBlank()) return

        // Prevent directory traversal
        fileName = fileName.substringAfterLast("/").substringAfterLast("\\")
        
        Log.i(TAG, "Starting to receive file: $fileName ($fileId)")

        val resolver = context.contentResolver
        val contentValues = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/DeviceLink")
        }

        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
        if (uri != null) {
            val outputStream = resolver.openOutputStream(uri)
            if (outputStream != null) {
                val notifId = fileId.hashCode()
                activeReceives[fileId] = TransferState(outputStream, fileName, fileSize, 0L, notifId)
                
                val notification = NotificationCompat.Builder(context, "nexus_file_transfer")
                    .setContentTitle("Receiving $fileName")
                    .setContentText("0%")
                    .setSmallIcon(android.R.drawable.stat_sys_download)
                    .setProgress(100, 0, fileSize <= 0L)
                    .setOngoing(true)
                    .build()
                notificationManager.notify(notifId, notification)
            } else {
                Log.e(TAG, "Failed to open OutputStream for $uri")
            }
        } else {
            Log.e(TAG, "Failed to insert into MediaStore")
        }
    }

    private fun handleFileChunk(payload: JSONObject) {
        val fileId = payload.optString("file_id")
        val dataB64 = payload.optString("data")
        
        val state = activeReceives[fileId] ?: return
        try {
            val bytes = Base64.decode(dataB64, Base64.NO_WRAP)
            state.stream.write(bytes)
            
            state.bytesReceived += bytes.size
            if (state.fileSize > 0) {
                val percent = ((state.bytesReceived.toDouble() / state.fileSize.toDouble()) * 100).toInt()
                // Update notification every few percent to avoid spamming
                if (percent % 5 == 0) {
                    val notification = NotificationCompat.Builder(context, "nexus_file_transfer")
                        .setContentTitle("Receiving ${state.fileName}")
                        .setContentText("$percent%")
                        .setSmallIcon(android.R.drawable.stat_sys_download)
                        .setProgress(100, percent, false)
                        .setOngoing(true)
                        .build()
                    notificationManager.notify(state.notificationId, notification)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to write chunk: ${e.message}")
        }
    }

    private fun handleTransferComplete(payload: JSONObject) {
        val fileId = payload.optString("file_id")
        val state = activeReceives.remove(fileId)
        if (state != null) {
            try {
                state.stream.close()
                Log.i(TAG, "File transfer complete: $fileId")
                
                val notification = NotificationCompat.Builder(context, "nexus_file_transfer")
                    .setContentTitle("File Received")
                    .setContentText(state.fileName)
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setAutoCancel(true)
                    .setOngoing(false)
                    .setProgress(0, 0, false)
                    .build()
                notificationManager.notify(state.notificationId, notification)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to close stream: ${e.message}")
            }
        }
    }

    fun sendFile(uri: Uri) {
        scope.launch {
            val resolver = context.contentResolver
            val fileId = UUID.randomUUID().toString()
            var fileName = "unknown_file"
            var fileSize = 0L

            resolver.query(uri, null, null, null, null)?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (cursor.moveToFirst()) {
                    if (nameIndex >= 0) fileName = cursor.getString(nameIndex)
                    if (sizeIndex >= 0) fileSize = cursor.getLong(sizeIndex)
                }
            }

            Log.i(TAG, "Sending file: $fileName, Size: $fileSize")

            // Send start
            val startPayload = JSONObject().apply {
                put("file_id", fileId)
                put("file_name", fileName)
                put("file_size", fileSize)
            }
            connectionManager.sendMessage("file_transfer_start", startPayload)

            // Stream chunks
            try {
                resolver.openInputStream(uri)?.use { inputStream ->
                    val buffer = ByteArray(CHUNK_SIZE)
                    var bytesRead: Int
                    var seq = 0
                    while (inputStream.read(buffer).also { bytesRead = it } != -1) {
                        val chunkBytes = if (bytesRead == CHUNK_SIZE) buffer else buffer.copyOfRange(0, bytesRead)
                        val b64 = Base64.encodeToString(chunkBytes, Base64.NO_WRAP)
                        
                        val chunkPayload = JSONObject().apply {
                            put("file_id", fileId)
                            put("sequence", seq++)
                            put("data", b64)
                        }
                        connectionManager.sendMessage("file_chunk", chunkPayload)
                    }
                }

                // Send complete
                val completePayload = JSONObject().apply {
                    put("file_id", fileId)
                }
                connectionManager.sendMessage("file_transfer_complete", completePayload)
                Log.i(TAG, "Sent file successfully: $fileName")

            } catch (e: Exception) {
                Log.e(TAG, "Failed to send file: \${e.message}")
            }
        }
    }
}
