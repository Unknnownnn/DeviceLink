"""
DeviceLink Windows Agent - Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# ── Identity / Persistence ─────────────────────────────────────────────────────
DEVICELINK_DIR = Path.home() / ".devicelink"
IDENTITY_KEY_PATH = DEVICELINK_DIR / "identity.key"
PEERS_DB_PATH = DEVICELINK_DIR / "peers.json"

# ── Networking ─────────────────────────────────────────────────────────────────
WS_HOST = "0.0.0.0"
WS_PORT = 47200                          # Default WebSocket port
MDNS_SERVICE_TYPE = "_devicelink._tcp.local."
MDNS_SERVICE_NAME = "DeviceLink"

# ── Protocol ───────────────────────────────────────────────────────────────────
PROTOCOL_VERSION = 1
HKDF_INFO = b"devicelink-session-v1"
HKDF_SALT = b"devicelink-hkdf-salt-v1"
SESSION_KEY_LEN = 32                     # 256-bit key for ChaCha20-Poly1305
NONCE_LEN = 12                           # 96-bit nonce

# ── AI Orchestrator ────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# ── Console UI ────────────────────────────────────────────────────────────────────
QR_BORDER = 1
QR_BOX_SIZE = 1                          # Console QR: each box = 1 char unit

# Ensure data directory exists on import
DEVICELINK_DIR.mkdir(parents=True, exist_ok=True)
