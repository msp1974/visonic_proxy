"""Handle commands."""

from collections.abc import Callable

from events import ALL_CLIENTS, Event, EventType

from .const import SEND_E0_MESSAGES
from .enums import ConnectionName, Mode
from .helpers import log_message
from .message import RoutableMessage
from .proxy import Proxy
from .transcoders.builder import MessageBuilder


class CommandManager:
    """Command Manager."""

    def __init__(self, proxy: Proxy):
        """Initialise."""
        self.proxy = proxy
        self.cb_send_message: Callable
        self._unsubscribe_listeners: list[Callable] = []

        self._message_builer = MessageBuilder(self.proxy)

    def start(self, send_callback: Callable):
        """Start command manager."""
        self.cb_send_message = send_callback

        # Subscribe to events
        self._unsubscribe_listeners.extend(
            [
                self.proxy.events.subscribe(
                    ALL_CLIENTS, EventType.SEND_KEEPALIVE, self.send_keepalive
                ),
            ]
        )
        log_message("Command Manager started", level=0)

    async def stop(self):
        """Stop command manager."""
        # Unsubscribe all events
        if self._unsubscribe_listeners:
            for unsub in self._unsubscribe_listeners:
                unsub()
        log_message("Command Manager stopped", level=0)

    async def send_keepalive(self, event: Event):
        """Handle sending keepalive."""
        log_message("Sending KeepAlive to %s %s", event.name, event.client_id, level=5)
        msg = self._message_builer.build_keep_alive_message()

        await self.cb_send_message(
            message=RoutableMessage(
                source=ConnectionName.CM,
                source_client_id=0,
                destination=event.name,
                destination_client_id=event.client_id,
                message=msg,
            ),
        )

    async def send_ack_message(self, message: RoutableMessage):
        """Send ACK message."""
        log_message(
            "Sending ACK to %s %s", message.source, message.source_client_id, level=5
        )
        msg = self._message_builer.build_ack_message(
            message.message.msg_id, not self.proxy.status.download_mode
        )

        await self.cb_send_message(
            message=RoutableMessage(
                source=ConnectionName.CM,
                source_client_id=0,
                destination=message.source,
                destination_client_id=message.source_client_id,
                message=msg,
            ),
            requires_ack=False,
        )

    async def send_init_message(self):
        """Send init message on Visonic connection."""
        log_message("Sending INIT to %s", ConnectionName.ALARM, level=5)
        msg = self._message_builer.message_preprocessor(
            bytes.fromhex("b0 17 51 0f"),
        )

        await self.cb_send_message(
            message=RoutableMessage(
                source=ConnectionName.CM,
                source_client_id=0,
                destination=ConnectionName.ALARM,
                destination_client_id=0,
                message=msg,
            ),
            requires_ack=True,
        )

    async def send_status_message(self):
        """Send an status message.

        Used to allow management of this Connection Manager from the Monitor Connection
        """
        if SEND_E0_MESSAGES:
            log_message("Sending STATUS to %s", ConnectionName.ALARM_MONITOR, level=5)
            status_msg = [
                "e0",
                f"{self.proxy.clients.count(ConnectionName.ALARM):02x}",
                f"{self.proxy.clients.count(ConnectionName.VISONIC):02x}",
                f"{self.proxy.clients.count(ConnectionName.ALARM_MONITOR):02x}",
                f"{"01" if self.proxy.status.proxy_mode else "00"}",
                f"{"01" if self.proxy.status.download_mode else "00"}",
                "43",
            ]
            msg = self._message_builer.message_preprocessor(
                bytes.fromhex(" ".join(status_msg))
            )

            await self.cb_send_message(
                message=RoutableMessage(
                    source=ConnectionName.CM,
                    source_client_id=0,
                    destination=ConnectionName.ALARM_MONITOR,
                    destination_client_id=0,
                    message=msg,
                ),
                requires_ack=False,
            )

    async def do_action_command(self, message: RoutableMessage):
        """Perform command from ACTION COMMAND message.

        Action message is 0a e1 <command> <value> 43 <checksum> 0d
        """
        command = message.message.data[2:3].hex()
        value = message.message.data[3:4].hex()

        if command == "01":  # Send status
            if self.proxy.clients.count(ConnectionName.ALARM_MONITOR) > 0:
                await self.send_status_message()
        elif command == "02":  # Enable/Disable stealth mode
            self.proxy.events.fire_event(
                Event(
                    name=ConnectionName.CM,
                    event_type=EventType.SET_MODE,
                    event_data={
                        Mode.STEALTH: value == "01"
                    },  # Enable if value is 01 else disable
                )
            )