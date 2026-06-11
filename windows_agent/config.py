import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DEVICELINK_DIR = Path.home() / ".devicelink"
IDENTITY_KEY_PATH = DEVICELINK_DIR / "identity.key"
PEERS_DB_PATH = DEVICELINK_DIR / "peers.json"

WS_HOST = "0.0.0.0"
WS_PORT = 47200                          
MDNS_SERVICE_TYPE = "_devicelink._tcp.local."
MDNS_SERVICE_NAME = "DeviceLink"
PROTOCOL_VERSION = 1
HKDF_INFO = b"devicelink-session-v1"
HKDF_SALT = b"devicelink-hkdf-salt-v1"
SESSION_KEY_LEN = 32                     
NONCE_LEN = 12                          
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
QR_BORDER = 1
QR_BOX_SIZE = 1                          
DEVICELINK_DIR.mkdir(parents=True, exist_ok=True)
