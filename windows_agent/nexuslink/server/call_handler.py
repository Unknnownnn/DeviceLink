import logging
from websockets.server import WebSocketServerProtocol

from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry, get_app_instance

log = logging.getLogger("nexuslink.call")

async def handle_incoming_call(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    number = msg.payload.get("number", "Unknown")
    name = msg.payload.get("name", "Unknown Caller")
    log.info("Incoming call from %s (%s)", name, number)

    app = get_app_instance()
    if app:
        app.after(0, lambda: app.show_call_overlay(number, name))
    else:
        log.warning("No GUI app instance registered. Cannot show call overlay.")

async def handle_call_status(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    status = msg.payload.get("status") 
    log.info("Call status update: %s", status)

    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_call_status_change(status))

async def handle_sync_contacts(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    contacts = msg.payload.get("contacts", [])
    log.info("Received %d contacts from phone", len(contacts))

    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_contacts(contacts))

async def handle_bt_status(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    connected = msg.payload.get("connected", False)
    log.info("Bluetooth connection status update: %s", connected)

    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_bt_status_change(connected))

def register(registry: HandlerRegistry) -> None:
    registry.register("incoming_call", handle_incoming_call)
    registry.register("call_status", handle_call_status)
    registry.register("sync_contacts", handle_sync_contacts)
    registry.register("bt_status", handle_bt_status)
