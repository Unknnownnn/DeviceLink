"""
DeviceLink Windows Agent — Entry Point

Starts the following concurrent services:
  1. Zeroconf mDNS publisher (announces '_devicelink._tcp.local.' on LAN)
  2. QR code display (for one-time device pairing)
  3. Encrypted WebSocket server (handles peer connections)

Usage:
    python main.py [--port PORT]
"""
from __future__ import annotations

import asyncio
import argparse
import logging
import sys
import os

# ── Make 'nexuslink' package importable from this directory ──────────────────
sys.path.insert(0, os.path.dirname(__file__))

from config import WS_PORT, WS_HOST
from nexuslink.identity import IdentityManager
from nexuslink.discovery import DiscoveryPublisher
from nexuslink.qr_provisioning import print_qr_to_console, save_qr_as_png
from nexuslink.server import NexusLinkServer


# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nexuslink.main")


# ── Main orchestration ────────────────────────────────────────────────────────

async def run(port: int) -> None:
    # 1. Load / generate device identity
    identity = IdentityManager()
    print(f"\n[Identity] Device fingerprint: {identity.fingerprint}")

    # 2. Show pairing QR code
    print_qr_to_console(identity.fingerprint, port)
    png_path = save_qr_as_png(identity.fingerprint, port)

    # 3. Set up services
    discovery = DiscoveryPublisher(port=port, fingerprint=identity.fingerprint)
    server = NexusLinkServer(identity=identity, host=WS_HOST, port=port)

    # 4. Start everything concurrently
    await discovery.start()
    await server.start()
    print(f"[QR] Pairing QR code saved to: {png_path}")

    print("\n[DeviceLink] Agent running. Waiting for Android connection…")
    print("[DeviceLink] Press Ctrl+C to stop.\n")

    try:
        # Keep running until interrupted
        await asyncio.Future()  # runs forever
    except asyncio.CancelledError:
        pass
    finally:
        print("\n[DeviceLink] Shutting down…")
        await discovery.stop()
        await server.stop()
        print("[DeviceLink] Goodbye.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeviceLink Windows Agent — Phase 1",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=WS_PORT,
        help="WebSocket server port",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(args.port))
    except KeyboardInterrupt:
        print("\n[DeviceLink] Interrupted.")


if __name__ == "__main__":
    main()
