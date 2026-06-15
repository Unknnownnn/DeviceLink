import socket
import struct
import os
import threading
import logging
import time
import json
import asyncio
import base64
from typing import Optional, Dict, Tuple
from nexuslink.models import NexusMessage, MsgType
from nexuslink.crypto import HandshakeManager, SessionCipher
from nexuslink.server.handlers import registry

log = logging.getLogger("nexuslink.udp_server")

active_udp_session = None
_udp_manager = None
_loop = None

def get_active_udp_session():
    global active_udp_session
    if active_udp_session:
        if time.time() - active_udp_session.get("last_seen", 0) > 12.0:
            log.info("UDP session timed out (no packets received for 12 seconds)")
            active_udp_session = None
            if _udp_manager:
                _udp_manager.reset_session()
    return active_udp_session

def get_active_udp_peer():
    session = get_active_udp_session()
    if session:
        return session["addr"]
    return None


class UdpSessionWrapper:
    def __init__(self, sock, addr, cipher):
        self.sock = sock
        self.addr = addr
        self.cipher = cipher
        self.remote_address = addr

    async def send(self, data: bytes) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.sock.sendto(data, self.addr))
            log.debug("Sent UDP packet to %s", self.addr)
        except Exception as e:
            log.error("Failed to send UDP packet to %s: %s", self.addr, e)

class UdpServerManager:
    def __init__(self, port: int, identity, on_session_established=None):
        self.port = port
        self.identity = identity
        self.on_session_established = on_session_established
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        
        # Bind socket
        try:
            self.sock.bind(("", port))
            log.info("UDP Server bound to port %d", port)
        except Exception as e:
            log.warning("UDP Server failed to bind to port %d: %s. Trying dynamic port.", port, e)
            self.sock.bind(("", 0))
            self.port = self.sock.getsockname()[1]
            log.info("UDP Server bound to dynamic port %d", self.port)

        self.running = True
        self.stun_host = "stun.l.google.com"
        self.stun_port = 19302
        
        self.stun_queries = {}
        self.peer_candidates = None
        self.handshake_manager = None
        self.session_cipher = None
        self.hole_punch_active = False
        
        self.peer_addr = None
        self.client_x25519_b64 = None
        self.client_ed25519_b64 = None

        self.listen_thread = threading.Thread(target=self._listen, daemon=True)
        self.listen_thread.start()

    def reset_session(self):
        log.info("Resetting UDP session and handshake state.")
        self.session_cipher = None
        self.peer_addr = None
        self.client_x25519_b64 = None
        self.client_ed25519_b64 = None
        self.handshake_manager = HandshakeManager()

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass

    def get_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    def query_stun(self) -> Optional[Tuple[str, int]]:
        tx_id = os.urandom(12)
        event = threading.Event()
        self.stun_queries[tx_id] = {"event": event, "result": None}
        
        # STUN Binding Request header (20 bytes)
        req = struct.pack("!HHI12s", 0x0001, 0x0000, 0x2112A442, tx_id)
        
        stun_targets = [
            ("173.194.202.127", 19302),
            ("74.125.143.127", 19302),
            ("108.177.119.127", 19302),
            ("54.172.47.199", 3478),
            ("stun.l.google.com", 19302),
            ("stun1.l.google.com", 19302),
            ("stun.chat.twilio.com", 3478),
            ("stun.sipgate.net", 10000)
        ]
        
        def send_request(host, port):
            try:
                addr_info = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
                if addr_info:
                    ip = addr_info[0][4][0]
                    self.sock.sendto(req, (ip, port))
            except Exception as e:
                log.debug("Failed to resolve/send STUN to %s: %s", host, e)

        for attempt in range(2):
            if not self.running:
                break
            for host, port in stun_targets:
                threading.Thread(target=send_request, args=(host, port), daemon=True).start()
            # Wait for any of the servers to set the result
            if event.wait(1.5):
                res = self.stun_queries[tx_id]["result"]
                del self.stun_queries[tx_id]
                return res
        
        if tx_id in self.stun_queries:
            del self.stun_queries[tx_id]
        return None

    def start_hole_punching(self, peer_candidates):
        self.peer_candidates = peer_candidates
        self.hole_punch_active = True
        self.peer_addr = None
        self.session_cipher = None
        self.handshake_manager = HandshakeManager()
        
        threading.Thread(target=self._send_hole_punch_packets, daemon=True).start()

    def _send_hole_punch_packets(self):
        log.info("Starting UDP hole punching loop towards candidates: %s", self.peer_candidates)
        destinations = []
        if self.peer_candidates:
            if "local_ip" in self.peer_candidates and self.peer_candidates["local_ip"]:
                destinations.append((self.peer_candidates["local_ip"], int(self.peer_candidates["local_port"])))
            if "public_ip" in self.peer_candidates and self.peer_candidates["public_ip"]:
                destinations.append((self.peer_candidates["public_ip"], int(self.peer_candidates["public_port"])))
        
        attempts = 0
        while self.running and self.hole_punch_active and attempts < 40:
            if self.peer_addr:
                break
            for dest in destinations:
                try:
                    self.sock.sendto(b"HOLE_PUNCH", dest)
                    log.debug("Sent HOLE_PUNCH to %s", dest)
                except Exception:
                    pass
            attempts += 1
            time.sleep(0.25)

    def _listen(self):
        global active_udp_session
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue
                
                # 1. Check if it's STUN response
                if len(data) >= 20 and struct.unpack("!I", data[4:8])[0] == 0x2112A442:
                    msg_type, msg_len, magic, rx_tx_id = struct.unpack("!HHI12s", data[:20])
                    if rx_tx_id in self.stun_queries:
                        pos = 20
                        res = None
                        while pos + 4 <= len(data):
                            attr_type, attr_len = struct.unpack("!HH", data[pos:pos+4])
                            pos += 4
                            if pos + attr_len > len(data):
                                break
                            attr_val = data[pos:pos+attr_len]
                            pos += (attr_len + 3) & ~3
                            
                            if attr_type == 0x0001:  # MAPPED-ADDRESS
                                if len(attr_val) >= 8:
                                    family = attr_val[1]
                                    if family == 0x01: # IPv4
                                        port = struct.unpack("!H", attr_val[2:4])[0]
                                        ip = socket.inet_ntoa(attr_val[4:8])
                                        res = (ip, port)
                                        break
                            elif attr_type in (0x0020, 0x8020):  # XOR-MAPPED-ADDRESS
                                if len(attr_val) >= 8:
                                    family = attr_val[1]
                                    if family == 0x01: # IPv4
                                        x_port = struct.unpack("!H", attr_val[2:4])[0]
                                        port = x_port ^ 0x2112
                                        x_ip = struct.unpack("!I", attr_val[4:8])[0]
                                        ip_int = x_ip ^ 0x2112A442
                                        ip = socket.inet_ntoa(struct.pack("!I", ip_int))
                                        res = (ip, port)
                                        break
                        if res:
                            self.stun_queries[rx_tx_id]["result"] = res
                            self.stun_queries[rx_tx_id]["event"].set()
                    continue

                # 2. Check if it's HOLE_PUNCH packet
                if data == b"HOLE_PUNCH":
                    log.info("Received HOLE_PUNCH from %s", addr)
                    self.sock.sendto(b"HOLE_PUNCH_ACK", addr)
                    if not self.peer_addr:
                        self.peer_addr = addr
                        log.info("UDP path punch succeeded to %s!", addr)
                    continue

                if data == b"HOLE_PUNCH_ACK":
                    log.info("Received HOLE_PUNCH_ACK from %s", addr)
                    if not self.peer_addr:
                        self.peer_addr = addr
                        log.info("UDP path punch succeeded to %s!", addr)
                    continue

                # 3. Check if it's handshake hello
                if data.startswith(b'{"type"'):
                    try:
                        msg = json.loads(data.decode("utf-8"))
                        if msg.get("type") == MsgType.HELLO:
                            log.info("Plaintext HELLO handshake packet received. Resetting UDP session.")
                            self.session_cipher = None
                            active_udp_session = None
                    except Exception:
                        pass

                if not self.session_cipher:
                    try:
                        plaintext_str = data.decode("utf-8")
                        msg = json.loads(plaintext_str)
                        msg_type = msg.get("type")
                        
                        if msg_type == MsgType.HELLO:
                            log.info("Received HELLO from UDP %s", addr)
                            self.peer_addr = addr
                            self.hole_punch_active = False
                            
                            payload = msg.get("payload", {})
                            client_x25519_b64 = payload.get("x25519_public_key")
                            client_ed25519_b64 = payload.get("ed25519_public_key")
                            
                            self.client_x25519_b64 = client_x25519_b64
                            self.client_ed25519_b64 = client_ed25519_b64
                            
                            my_x25519_pub_raw = _b64url_decode(self.handshake_manager.public_key_b64)
                            client_x25519_raw = _b64url_decode(client_x25519_b64)
                            
                            transcript_to_sign = my_x25519_pub_raw + client_x25519_raw
                            signature_raw = self.identity.sign(transcript_to_sign)
                            signature_b64 = base64_url_encode(signature_raw)
                            
                            hello_ack = NexusMessage(
                                type=MsgType.HELLO_ACK,
                                payload={
                                    "x25519_public_key": self.handshake_manager.public_key_b64,
                                    "ed25519_public_key": self.identity.public_key_b64,
                                    "signature": signature_b64,
                                    "device_name": socket.gethostname(),
                                },
                            )
                            self.sock.sendto(hello_ack.to_bytes(), addr)
                            log.info("Sent HELLO_ACK to UDP %s", addr)
                            continue

                        elif msg_type == MsgType.HELLO_CONFIRM:
                            log.info("Received HELLO_CONFIRM from UDP %s", addr)
                            payload = msg.get("payload", {})
                            client_sig_raw = _b64url_decode(payload.get("signature"))
                            
                            client_x25519_raw = _b64url_decode(self.client_x25519_b64)
                            my_x25519_pub_raw = _b64url_decode(self.handshake_manager.public_key_b64)
                            
                            transcript_expected = client_x25519_raw + my_x25519_pub_raw
                            client_ed25519_raw = _b64url_decode(self.client_ed25519_b64)
                            
                            if _verify_ed25519(client_ed25519_raw, transcript_expected, client_sig_raw):
                                log.info("UDP Handshake confirmed! Signature verified.")
                                session_key = self.handshake_manager.derive_session_key(self.client_x25519_b64)
                                self.session_cipher = SessionCipher(session_key)
                                
                                active_udp_session = {
                                    "addr": addr,
                                    "socket": self.sock,
                                    "cipher": self.session_cipher,
                                    "last_seen": time.time()
                                }
                                print(f"[Server] ✓ Secure session active via STUN/UDP Hole Punching: {addr}")
                                log.info("Secure UDP session established with %s", addr)
                                
                                if self.on_session_established:
                                    self.on_session_established(addr, self.session_cipher)
                            else:
                                log.warning("UDP HELLO_CONFIRM signature verification FAILED")
                            continue

                    except Exception as e:
                        log.warning("Handshake parsing/processing failed: %s", e)
                        continue

                # 4. Decrypt and handle data packets
                try:
                    plaintext = self.session_cipher.decrypt(data)
                    if active_udp_session:
                        active_udp_session["last_seen"] = time.time()
                    else:
                        active_udp_session = {
                            "addr": addr,
                            "socket": self.sock,
                            "cipher": self.session_cipher,
                            "last_seen": time.time()
                        }
                    msg = NexusMessage.from_bytes(plaintext)
                    log.debug("→ (UDP) [%s] %s", msg.type, msg.id)
                    
                    if _loop:
                        wrapper = UdpSessionWrapper(self.sock, addr, self.session_cipher)
                        asyncio.run_coroutine_threadsafe(registry.dispatch(msg, self.session_cipher, wrapper), _loop)
                except Exception as e:
                    log.debug("Failed to decrypt UDP packet: %s", e)

            except Exception as e:
                if self.running:
                    log.warning("UDP listener error: %s", e)
                    time.sleep(0.1)

def _b64url_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)

def base64_url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _verify_ed25519(pub_key_raw: bytes, message: bytes, signature: bytes) -> bool:
    from nacl.signing import VerifyKey
    try:
        VerifyKey(pub_key_raw).verify(message, signature)
        return True
    except Exception:
        return False
