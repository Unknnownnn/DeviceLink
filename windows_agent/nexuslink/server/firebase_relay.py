import threading
import json
import requests
import sseclient
import time
import base64
import os
import hashlib
import logging

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

log = logging.getLogger("nexuslink.firebase_relay")

class FirebaseRelay:
    def __init__(self, db_url, fingerprint, on_message_callback):
        self.db_url = db_url.rstrip('/')
        self.fingerprint = fingerprint
        self.on_message_callback = on_message_callback
        self.running = True
        self.heartbeat_enabled = False
        self._next_heartbeat_at = 0.0
        
        self.aes_key = hashlib.sha256(fingerprint.encode('utf-8')).digest()
        self.session = requests.Session()
        
        self.listen_thread = threading.Thread(target=self._listen, daemon=True)
        self.listen_thread.start()
        
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.heartbeat_thread.start()
        
        log.info("Firebase relay started listening for %s", fingerprint[:8])

    def stop(self):
        self.running = False
        self.heartbeat_enabled = False

    def start_heartbeat(self):
        self.heartbeat_enabled = True
        self._next_heartbeat_at = time.time() + 60
        self._send_heartbeat()

    def stop_heartbeat(self):
        self.heartbeat_enabled = False

    def _heartbeat(self):
        while self.running:
            try:
                if self.heartbeat_enabled:
                    now = time.time()
                    if now >= self._next_heartbeat_at:
                        self._send_heartbeat()
                        self._next_heartbeat_at = now + 60
            except Exception as e:
                pass
            time.sleep(1)

    def _send_heartbeat(self):
        url = f"{self.db_url}/devices/{self.fingerprint}/pc_online.json"
        self.session.put(url, json={"timestamp": int(time.time() * 1000)}, timeout=5)

    def encrypt(self, data: bytes) -> str:
        if not AESGCM: return base64.b64encode(data).decode('utf-8')
        nonce = os.urandom(12)
        aesgcm = AESGCM(self.aes_key)
        ct = aesgcm.encrypt(nonce, data, None)
        return base64.b64encode(nonce + ct).decode('utf-8')

    def decrypt(self, b64_str: str) -> bytes:
        if not AESGCM: return base64.b64decode(b64_str)
        try:
            raw = base64.b64decode(b64_str)
            nonce = raw[:12]
            ct = raw[12:]
            aesgcm = AESGCM(self.aes_key)
            return aesgcm.decrypt(nonce, ct, None)
        except Exception as e:
            log.warning("Firebase decrypt failed: %s", e)
            return b""

    def _listen(self):
        url = f"{self.db_url}/devices/{self.fingerprint}/to_pc.json"
        while self.running:
            try:
                # Use a connect timeout of 10s and read timeout of 45s to detect half-open sockets (VPN/network drops)
                response = self.session.get(url, headers={'Accept': 'text/event-stream'}, stream=True, timeout=(10, 45))
                if response.status_code != 200:
                    log.warning("Firebase listener HTTP status %d, retrying...", response.status_code)
                    time.sleep(5)
                    continue

                client = sseclient.SSEClient(response)
                for event in client.events():
                    if not self.running:
                        break
                    if event.event == 'put':
                        try:
                            data = json.loads(event.data)
                        except:
                            continue

                        path = data.get("path", "")
                        payload = data.get("data")
                        
                        if payload is None:
                            continue
                        
                        if path == "/":
                            if isinstance(payload, dict):
                                for key, msg in payload.items():
                                    if msg:
                                        self._process_msg(key, msg)
                        else:
                            key = path.strip("/")
                            self._process_msg(key, payload)
            except Exception as e:
                log.warning("Firebase listener exception: %s. Retrying in 5 seconds...", e)
                time.sleep(5)

    def _process_msg(self, key, msg_str):
        try:
            plaintext = self.decrypt(msg_str)
            if plaintext:
                self.on_message_callback(plaintext)
        except Exception as e:
            pass
            
        delete_url = f"{self.db_url}/devices/{self.fingerprint}/to_pc/{key}.json"
        try:
            self.session.delete(delete_url, timeout=5)
        except:
            pass

    def send_to_phone(self, data: bytes):
        url = f"{self.db_url}/devices/{self.fingerprint}/to_phone.json"
        try:
            encrypted_b64 = self.encrypt(data)
            self.session.post(url, json=encrypted_b64, timeout=5)
        except Exception as e:
            log.warning("Firebase send failed: %s", e)
