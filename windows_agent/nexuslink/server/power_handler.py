import logging
import os
import ctypes
from websockets.server import WebSocketServerProtocol

from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry
from nexuslink.server.agent_orchestrator import SanitizationSandbox

log = logging.getLogger("nexuslink.power")

async def handle_power_command(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    action = msg.payload.get("action")
    log.info("Received power command: %s", action)

    if action == "lock":
        # Lock workstation
        ctypes.windll.user32.LockWorkStation()
    elif action == "sleep":
        # Put Windows to sleep (SuspendState)
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    elif action == "shutdown":
        # Shutdown in 0 seconds
        os.system("shutdown /s /t 0")
    else:
        log.warning("Unknown power action: %s", action)


async def handle_launch_app(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    app_name = msg.payload.get("app_name")
    log.info("Received launch command: %s", app_name)
    
    # Reuse our existing safe sandbox
    sandbox = SanitizationSandbox()
    result = sandbox.launch_approved_application(app_name)
    log.info("Launch result: %s", result)


def register(registry: HandlerRegistry) -> None:
    registry.register("power_command", handle_power_command)
    registry.register("launch_app", handle_launch_app)
