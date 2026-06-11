# DeviceLink

DeviceLink is a self-hosted, end-to-end encrypted bridge between a Windows PC and an Android device. It operates entirely on the local network with no cloud dependency. Communication is secured with a mutually authenticated handshake and per-session AEAD encryption. An AI agent on the Windows side can accept natural-language commands from the Android app to launch applications, perform searches, and interact with the PC.

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
- [Project Structure](#project-structure)
- [Building the Windows Executable](#building-the-windows-executable)

---

## Features

- **Bidirectional clipboard sync** - Copy on one device, paste on the other. Windows detection uses a native Win32 event hook (`AddClipboardFormatListener`) for zero idle CPU cost.
- **File drop zone** - Drop files into a watched folder on the PC to send them to the Android device over the encrypted channel.
- **Mobile deck shortcuts** - Define custom shortcut buttons on the Android app that trigger actions on the PC.
- **AI agent** - Send natural-language commands from the phone. The agent can search for and launch applications, open URLs, and interact with the PC without requiring every action to be pre-approved.
- **System tray integration** - The Windows agent runs minimised to the tray with no persistent console window.
- **No cloud, no accounts** - All traffic stays on the local network. Pairing is done once via QR code.

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

### Windows Agent

1. Clone the repository.

   ```
   git clone https://github.com/your-username/DeviceLink.git
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

4. (Optional) Create a `.env` file for AI agent configuration.

   ```
   OPENROUTER_API_KEY=your_key_here
   OPENROUTER_MODEL=anthropic/claude-sonnet-4-5
   ```

5. Run the agent.

   ```
   python DeviceLink.pyw
   ```

### Android App

Open `android_app/` in Android Studio, build the project, and install the APK on your device. The app requires no additional configuration before pairing.

---

## Pairing

1. Start the Windows agent. The QR code is displayed in the application window.
2. Open the Android app and tap **Scan QR Code**.
3. Point the camera at the QR code displayed on the PC.

The Android device is now registered as a trusted peer. Future connections on the same local network are made automatically.

---

## AI Agent

The agent is powered by a language model accessed via the [OpenRouter](https://openrouter.ai) API. It accepts natural-language commands from the Android app and executes them using a set of built-in tools.

### Available Tools

| Tool | Description |
|---|---|
| `search_for_application` | Searches the Desktop, Start Menu, and user-defined directories for an application by name |
| `launch_application` | Launches an executable, shortcut (`.lnk`), or URL file by absolute path |
| `open_url` | Opens a URL in the default browser |
| `get_system_info` | Returns basic system information (OS, CPU, RAM) |
| `list_running_processes` | Lists currently running processes |

### Guardrails

The agent will not execute commands that:

- Target protected system directories (`System32`, `Windows`, `Program Files`, etc.)
- Delete or modify files outside explicitly permitted paths
- Invoke blocked shell binaries (`cmd.exe`, `powershell.exe`, and equivalents)

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

