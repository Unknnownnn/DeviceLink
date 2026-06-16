# DeviceLink

DeviceLink is a self-hosted, end-to-end encrypted bridge between a Windows PC and an Android device. It can operate entirely on the local network using mDNS, use WebRTC with UDP punching as a fallback when mDNS isnt available or via a secure cloud relay as a second fallback when UDP fails. Communication is secured with a mutually authenticated handshake and per-session encryption using ChaCha20-Poly1305 algorithm. You can configure an AI agent on the Windows side can accept natural-language commands from the Android app to launch applications, perform searches, and interact with the PC or vice versa on your phone. DeviceLink also includes custom desktop deck, notification mirroring, sms mirroring, and more on Windows to interact with your android device and a custom app deck, power options, AI agent on your phone to launch your PC apps instantly with your android device.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Security](#security)
- [Requirements](#requirements)
- [Setup](#setup)
  - [Windows Agent](#windows-agent)
  - [Android App](#android-app)
- [Pairing](#pairing)
- [AI Agent](#ai-agent)
- [Configuration](#configuration)
- [Building the Windows Executable](#building-the-windows-executable)

---

## Features

- **Bidirectional clipboard sync** - Copy on one device, paste on the other. Windows detection uses a native Win32 event hook (`AddClipboardFormatListener`) for zero idle CPU cost.
- **Direct file sharing** - Send files directly from the Windows dashboard or Android app. The transfer runs over direct, secure local channels (WebSocket or UDP) with real-time progress bars.
- **Mobile deck shortcuts** - Define custom shortcut buttons on the Android app that trigger actions on the PC.
- **AI agent** - Send natural-language commands from the phone. The agent can search for and launch applications, open URLs, and interact with the PC without requiring every action to be pre-approved.
- **AI-Powered Mobile Control** - The AI agent is equipped with a remote device control tool to launch apps, toggle the basic settings, and adjust ring/media volume on the connected Android phone.
- **System tray integration** - The Windows agent runs minimised to the tray with no persistent console window.
- **Phone Status Synchronization** - Monitor phone status such as battery percentage, charging state, network connection type, Wi-Fi SSID, and Bluetooth connection status in real-time on the PC dashboard.
- **Notification & SMS Mirroring** - Synchronize and view incoming Android app notifications and browse SMS threads directly on the Windows dashboard.
- **Desktop Deck Integration** - Custom mobile deck widgets reside in a overlay grid frame, allowing the synced phone wallpaper to show through without visual blockiness.
- **As secure as you want** - Features a collapsible permission manager allowing users to give it only the permissions they want to.
- **No cloud, no accounts** - All traffic stays on the local network. Pairing is done once via QR code. Cloud relay fallback only uses encrypted messages to send commands and deletes them within 5 minutes. ANDROID MIRRORING , ANDROID CONTROLS & PHONE CONTACTS are NOT AVAIALABLE when connected via cloud relay.

---

## Architecture

```
Android App                                               Windows Agent
-----------                                               -------------
ConnectionManager ─── WebSocket (TLS-equivalent AEAD) ─── NexusLinkServer
NexusWebSocketClient                                        ws_server.py
                                                               |
                                                  ┌────────────┼────────────┐
                                                  │            │            │
                                            clipboard     file handler  agent orchestrator
                                             handler      (chunked      (OpenRouter LLM  
                                            (Win32 hook)   transfer)     + tool loop)
                                                           
```

The Android app connects to the Windows agent over WebSocket on the local network. Both sides perform an X25519 ECDH handshake on every new session and derive a fresh ChaCha20-Poly1305 session key. The Android device is identified by a persistent Ed25519 identity key, which is verified during the handshake.

mDNS (Zeroconf) is used on the Windows side to advertise the service on `_devicelink._tcp.local.`, allowing the Android app to discover the PC automatically without entering an IP address.

---

## Security

| Property | Implementation |
|---|---|
| Key exchange | X25519 ECDH (ephemeral per-session) |
| Key derivation | HKDF-SHA256 (RFC 5869) |
| Session encryption | ChaCha20-Poly1305 IETF (RFC 8439) |
| Peer authentication | Ed25519 signature over the DH transcript |
| Pairing | QR code containing the server's Ed25519 public key and address |
| Transport | Binary WebSocket frames, each carrying `nonce || ciphertext || tag` |

No session key is reused across connections. A new ephemeral X25519 key pair is generated for every session. The 28-byte overhead per message (12-byte nonce + 16-byte Poly1305 tag) is the only protocol cost beyond the payload.

Pairing binds an Android device's Ed25519 public key to the Windows agent's peer store. Subsequent connections are authenticated without re-scanning the QR code.

---

## Requirements

### Windows Agent

- Windows 10 or later (64-bit)
- Python 3.11 or later

### Android App

- Android 8.0 (API 26) or later

---

## Setup

### Download the latest windows binary and android apk via the releases tab from the offical github repo:
- https://github.com/Unknnownnn/DeviceLink/releases   

The apps include auto-updating features and automatically fetch the latest release when available.



### Below are the instructions on how to build your own binaries via the source code
### Windows Agent

1. Clone the repository.

   ```
   git clone https://github.com/Unknnownnn/DeviceLink.git
   cd DeviceLink/windows_agent
   ```

2. Create and activate a virtual environment.

   ```
   python -m venv venv
   venv\Scripts\activate
   ```

3. Install dependencies.

   ```
   pip install -r requirements.txt
   ```

4. Run the agent.

   ```
   python DeviceLink.pyw
   ```

5. Build the .exe file by running

   ```
   build.bat
   ```

### Android App

Open `android_app/` in Android Studio, build the project, and install the APK on your device. The app requires no additional configuration before pairing.

---

## Pairing

1. Start the Windows agent. The QR code is displayed in the application window.
2. Open the Android app and tap **Scan QR Code**.
3. Point the camera at the QR code displayed on the PC.

The Android device is now registered as a trusted peer. Future connections on the same local network are made automatically. When local connection is not possible, the connection can be made via UDP Hole punching or cloud relay (limited functionality).

---

## AI Agent

The agent is powered by a language model accessed via the [OpenRouter](https://openrouter.ai) API. It accepts natural-language commands and executes them using a set of built-in tools. You can add various whitelisted directories for it to use while executing tasks.

### Available Tools

| Tool | Description |
|---|---|
| `search_for_application` | Searches the Desktop, Start Menu, and user-defined directories for an application by name |
| `launch_application` | Launches an executable, shortcut (`.lnk`), or URL file by absolute path |
| `open_url` | Opens a URL in the default browser |
| `get_system_info` | Returns basic system information (OS, CPU, RAM) |
| `list_running_processes` | Lists currently running processes |
| `control_android_device` | Launches apps, toggles flashlight/torch, or controls media/ring volume on the connected Android device |

### Guardrails

The agent will not execute commands that:

- Target protected system directories (`System32`, `Windows`, `Program Files`, etc.)
- Delete or modify files outside explicitly permitted paths
- Invoke blocked shell binaries (`cmd.exe`, `powershell.exe`, and equivalents)
- Access or process sensitive user records like notifications, SMS messages, contacts, or call logs (strict privacy boundaries)

If a command requires administrator privileges, the agent uses UAC elevation via `ShellExecuteW` with the `runas` verb.

### Search Directories

The agent searches the following locations by default:

- `C:\Users\<user>\Desktop`
- `C:\Users\Public\Desktop`
- `C:\ProgramData\Microsoft\Windows\Start Menu\Programs`
- Directories listed under **Allowed Launch Directories** in the application settings

Custom directories (e.g. `D:\`, `C:\Games`) can be added through the Settings tab in the application window.

---

## Configuration

All runtime configuration lives in `windows_agent/config.py` and can be overridden via a `.env` file placed in the `windows_agent/` directory.

| Key | Default | Description |
|---|---|---|
| `WS_PORT` | `47200` | WebSocket server port |
| `OPENROUTER_API_KEY` | _(empty)_ | API key for the AI agent |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | Model identifier passed to OpenRouter |

Persistent data (identity keys, peer records, settings) is stored in `%USERPROFILE%\.devicelink\`.

---

## Building the Windows Executable

A self-contained `.exe` can be produced with PyInstaller. Run the following from within the activated virtual environment:

```
pyinstaller --noconsole --onefile --collect-all customtkinter --hidden-import=_cffi_backend --icon=icon.ico --add-data "icon.ico;." --add-data "icon.png;." --name DeviceLink DeviceLink.pyw
```

The output is placed in `windows_agent/dist/DeviceLink.exe`. No Python installation is required on the target machine.

---

