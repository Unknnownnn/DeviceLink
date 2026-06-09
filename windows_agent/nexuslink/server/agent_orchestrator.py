import asyncio
import json
import logging
import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, Any, List

import aiohttp
from websockets.server import WebSocketServerProtocol

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry

log = logging.getLogger("nexuslink.orchestrator")


class SanitizationSandbox:
    """
    Executes tool calls strictly ensuring path-jailing and process whitelisting.
    NEVER uses shell=True.
    """
    
    # Pre-approved applications to strictly avoid arbitrary execution
    APPROVED_APPS = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
        "explorer": "explorer.exe"
    }

    # Steam Game AppIDs for URI routing
    STEAM_GAMES = {
        "dota 2": "570",
        "cs2": "730",
        "monster hunter": "582010",
        "cyberpunk 2077": "1091500",
        "elden ring": "1245620",
    }

    @staticmethod
    def _resolve_safe_path(relative_path: str) -> Path:
        """Resolves a relative path strictly within the user's home profile."""
        base_path = Path.home()
        # Clean relative path to avoid absolute injection
        clean_rel = relative_path.lstrip("\\/")
        target = (base_path / clean_rel).resolve()
        
        # Path jailing check
        if not target.is_relative_to(base_path):
            raise PermissionError(f"Path traversal detected! {target} is outside of user profile.")
        return target

    def create_local_directory(self, relative_path: str) -> str:
        try:
            target = self._resolve_safe_path(relative_path)
            if target.exists():
                return f"Directory already exists: {target}"
            target.mkdir(parents=True, exist_ok=True)
            return f"Successfully created directory: {target}"
        except Exception as e:
            return f"Failed to create directory: {e}"

    def count_directory_files(self, relative_path: str) -> str:
        try:
            target = self._resolve_safe_path(relative_path)
            if not target.exists() or not target.is_dir():
                return f"Target is not a valid directory: {target}"
            
            # Non-recursive count of files
            count = sum(1 for item in target.iterdir() if item.is_file())
            return f"Found {count} files in {target}"
        except Exception as e:
            return f"Failed to count files: {e}"

    def launch_approved_application(self, target_name: str) -> str:
        try:
            name_lower = target_name.lower().strip()
            
            # 1. Check native Windows apps
            if name_lower in self.APPROVED_APPS:
                exe = self.APPROVED_APPS[name_lower]
                # No shell=True. Exact mapping lookup array.
                subprocess.Popen([exe], shell=False)
                return f"Successfully launched local app: {name_lower}"

            # 2. Check Steam games
            if name_lower in self.STEAM_GAMES:
                app_id = self.STEAM_GAMES[name_lower]
                uri = f"steam://run/{app_id}"
                # Sidestep execution risk by delegating strictly to URI handler
                webbrowser.open(uri)
                return f"Successfully routed launch request for Steam game: {name_lower}"

            return f"Rejected: '{target_name}' is not in the approved application whitelist."
        except Exception as e:
            return f"Failed to launch application: {e}"


class OpenRouterAgent:
    TOOLS_SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "create_local_directory",
                "description": "Creates a new folder at a relative path inside the user standard profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Relative directory layout string, e.g., 'Documents/Projects/App'"}
                    },
                    "required": ["relative_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "count_directory_files",
                "description": "Returns the integer count of files residing within an approved sub-folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Relative directory layout string, e.g., 'Downloads'"}
                    },
                    "required": ["relative_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "launch_approved_application",
                "description": "Launches a locally whitelisted application wrapper or a native Steam game via target URI routing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_name": {"type": "string", "description": "The common name of the application or game, e.g., 'notepad', 'monster hunter'"}
                    },
                    "required": ["target_name"]
                }
            }
        }
    ]

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.sandbox = SanitizationSandbox()

    async def execute_command(self, prompt: str) -> str:
        if not self.api_key:
            return "Server Error: OPENROUTER_API_KEY is not configured on the Windows agent."

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": "You are a secure Windows automation assistant. Map the user's natural language intent directly to one of the available tool functions. Do not hallucinate tools or arguments."},
                {"role": "user", "content": prompt}
            ],
            "tools": self.TOOLS_SCHEMA,
            "tool_choice": "auto"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload) as response:
                    if response.status != 200:
                        text = await response.text()
                        log.error("OpenRouter API error: %s", text)
                        return f"AI API Error: HTTP {response.status}"
                    
                    data = await response.json()
                    
                    choices = data.get("choices", [])
                    if not choices:
                        return "AI Error: Received empty response from model."
                        
                    message = choices[0].get("message", {})
                    
                    tool_calls = message.get("tool_calls", [])
                    if tool_calls:
                        results = []
                        for call in tool_calls:
                            func = call.get("function", {})
                            name = func.get("name")
                            args_str = func.get("arguments", "{}")
                            
                            try:
                                args = json.loads(args_str)
                            except json.JSONDecodeError:
                                args = {}

                            log.info("Agent executing tool: %s(%s)", name, args)
                            
                            if name == "create_local_directory":
                                res = self.sandbox.create_local_directory(args.get("relative_path", ""))
                                results.append(res)
                            elif name == "count_directory_files":
                                res = self.sandbox.count_directory_files(args.get("relative_path", ""))
                                results.append(res)
                            elif name == "launch_approved_application":
                                res = self.sandbox.launch_approved_application(args.get("target_name", ""))
                                results.append(res)
                            else:
                                results.append(f"Security Alert: Model attempted to call unauthorized tool '{name}'")
                                
                        return "\n".join(results)
                    
                    content = message.get("content")
                    if content:
                        return f"AI response: {content}"
                        
                    return "Command processed, but no actionable operations were matched."

        except Exception as e:
            log.exception("Error executing AI command")
            return f"Agent Error: {e}"

agent = OpenRouterAgent(OPENROUTER_API_KEY)

async def handle_nlp_command(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    prompt = msg.payload.get("prompt", "")
    log.info("Received NLP command: %s", prompt)
    
    result_text = await agent.execute_command(prompt)
    log.info("NLP Result: %s", result_text)
    
    response_msg = NexusMessage(
        type="nlp_response",
        payload={"result": result_text, "prompt": prompt}
    )
    await ws.send(cipher.encrypt(response_msg.to_bytes()))


def register(registry: HandlerRegistry) -> None:
    registry.register("nlp_command", handle_nlp_command)
