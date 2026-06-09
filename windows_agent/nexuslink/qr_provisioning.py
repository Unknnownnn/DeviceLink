"""
DeviceLink QR Provisioning

Renders a QR code to the terminal (and optionally a PNG file) containing
the agent's identity fingerprint and network address.  The Android app
scans this QR code to initiate the one-time pairing flow.

QR payload JSON:
    {
        "v":    1,
        "fp":   "<sha256-hex of Ed25519 public key>",
        "host": "<local hostname>",
        "port": <ws_port>
    }
"""
from __future__ import annotations

import json
import socket
from io import StringIO

import qrcode
from qrcode.image.pure import PyPNGImage

from config import WS_PORT, DEVICELINK_DIR


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"

def build_pairing_payload(fingerprint: str, port: int = WS_PORT) -> str:
    """Return the JSON string to embed in the QR code."""
    data = {
        "v": 1,
        "fp": fingerprint,
        "host": get_local_ip(),
        "port": port,
    }
    return json.dumps(data, separators=(",", ":"))


def print_qr_to_console(fingerprint: str, port: int = WS_PORT) -> None:
    """
    Render the pairing QR code directly in the terminal using block characters.
    Works on any terminal that supports Unicode block elements.
    """
    payload = build_pairing_payload(fingerprint, port)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    # Print header
    print()
    print("=" * 60)
    print("  DeviceLink — Scan this QR code with the Android app to pair")
    print("=" * 60)

    # Render using the built-in ASCII art method (terminal-friendly)
    f = StringIO()
    qr.print_ascii(out=f, invert=True)
    f.seek(0)
    print(f.read())

    print("=" * 60)
    print(f"  Fingerprint: {fingerprint[:16]}…{fingerprint[-8:]}")
    print(f"  Host: {socket.gethostname()}   Port: {port}")
    print("=" * 60)
    print()


def save_qr_as_png(fingerprint: str, port: int = WS_PORT) -> str:
    """
    Save the pairing QR code as a PNG file in the DeviceLink data directory.
    Returns the file path as a string.
    """
    payload = build_pairing_payload(fingerprint, port)
    out_path = DEVICELINK_DIR / "pairing_qr.png"

    img = qrcode.make(payload)
    img.save(str(out_path))

    print(f"[QR] Pairing QR code saved to: {out_path}")
    return str(out_path)
