from __future__ import annotations

import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from config import WS_PORT, WS_HOST
from nexuslink.identity import IdentityManager
from nexuslink.discovery import DiscoveryPublisher
from nexuslink.qr_provisioning import print_qr_to_console, save_qr_as_png
from nexuslink.server import NexusLinkServer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nexuslink.main")

async def run(port: int) -> None:
    identity = IdentityManager()
    print(f"\n[Identity] Device fingerprint: {identity.fingerprint}")
    print_qr_to_console(identity.fingerprint, port)
    png_path = save_qr_as_png(identity.fingerprint, port)

    discovery = DiscoveryPublisher(port=port, fingerprint=identity.fingerprint)
    server = NexusLinkServer(identity=identity, host=WS_HOST, port=port)

    await discovery.start()
    await server.start()
    print(f"[QR] Pairing QR code saved to: {png_path}")
    print("\n[DeviceLink] Agent running. Waiting for Android connection…")

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        print("\n[DeviceLink] Shutting down…")
        await discovery.stop()
        await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeviceLink Windows Agent",
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