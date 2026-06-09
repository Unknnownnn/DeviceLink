"""
NexusLink mDNS Discovery Publisher

Broadcasts a '_nexuslink._tcp.local.' Zeroconf service so Android clients
can discover this PC without any manual IP entry.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Optional

from zeroconf import IPVersion, ServiceInfo, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

from config import MDNS_SERVICE_TYPE, MDNS_SERVICE_NAME, WS_PORT

log = logging.getLogger("nexuslink.discovery")


class DiscoveryPublisher:
    """
    Publishes a Zeroconf mDNS service entry for this NexusLink agent.

    The TXT record carries:
      - ``v``  : Protocol version
      - ``fp`` : Ed25519 public key fingerprint (hex SHA-256)
    """

    def __init__(self, port: int = WS_PORT, fingerprint: str = "") -> None:
        self._port = port
        self._fingerprint = fingerprint
        self._zeroconf: Optional[AsyncZeroconf] = None
        self._service_info: Optional[ServiceInfo] = None

    # ── Public API ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        hostname = socket.gethostname()
        local_ip = self._get_local_ip()
        SERVICE_TYPE = "_devicelink._tcp.local."
        service_name = f"DeviceLink_{socket.gethostname()}.{SERVICE_TYPE}"

        self._service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self._port,
            properties={
                b"v": b"1",
                b"fp": self._fingerprint.encode(),
                b"host": hostname.encode(),
            },
            server=f"{hostname}.local.",
        )

        self._zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self._zeroconf.async_register_service(self._service_info)

        log.info(
            "mDNS service registered: %s  [%s:%d]",
            service_name, local_ip, self._port,
        )
        print(
            f"[Discovery] mDNS service '{service_name}' → {local_ip}:{self._port}"
        )

    async def stop(self) -> None:
        if self._zeroconf and self._service_info:
            await self._zeroconf.async_unregister_service(self._service_info)
            await self._zeroconf.async_close()
            log.info("mDNS service unregistered.")

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _get_local_ip() -> str:
        """
        Attempt to determine the machine's LAN IP by probing a remote address
        (no actual packet is sent).
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
