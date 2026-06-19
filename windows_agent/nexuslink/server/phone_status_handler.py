import logging
from websockets.server import WebSocketServerProtocol

from nexuslink.crypto.session import SessionCipher
from nexuslink.models import NexusMessage
from nexuslink.server.handlers import HandlerRegistry

log = logging.getLogger("nexuslink.phone_status")

async def handle_sync_phone_status(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received phone status update from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_phone_status(msg.payload))
    else:
        log.warning("No GUI app instance registered. Cannot dispatch phone status.")

async def handle_sync_notifications(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received notifications update from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_notifications(msg.payload))

async def handle_sync_sms(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received SMS list update from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_sms(msg.payload))

async def handle_sync_desktop_deck(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received desktop deck update from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_desktop_deck(msg.payload))

async def handle_sync_gallery(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received gallery update from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_sync_gallery(msg.payload))

async def handle_delete_gallery_response(
    msg: NexusMessage, cipher: SessionCipher, ws: WebSocketServerProtocol
) -> None:
    log.info("Received delete gallery response from phone")
    from nexuslink.server.handlers import get_app_instance
    app = get_app_instance()
    if app:
        app.after(0, lambda: app.handle_delete_gallery_response(msg.payload))

def register(registry: HandlerRegistry) -> None:
    registry.register("sync_phone_status", handle_sync_phone_status)
    registry.register("sync_notifications", handle_sync_notifications)
    registry.register("sync_sms", handle_sync_sms)
    registry.register("sync_desktop_deck", handle_sync_desktop_deck)
    registry.register("sync_gallery", handle_sync_gallery)
    registry.register("delete_gallery_response", handle_delete_gallery_response)
