"""Client connection class."""

import asyncio
from collections.abc import Callable
import datetime as dt
import logging
from socket import AF_INET
import traceback

from ..const import VIS_ACK
from ..events import Event, EventType
from ..helpers import log_message
from ..message import QueuedMessage
from ..proxy import Proxy
from .protocol import ConnectionProtocol
from .watchdog import Watchdog

_LOGGER = logging.getLogger(__name__)


class ClientConnection:
    """Handles connection to visonic."""

    def __init__(
        self,
        proxy: Proxy,
        name: str,
        host: str,
        port: int,
        parent_connection_id: str,
        data_received_callback: Callable | None = None,
        run_watchdog: bool = False,
        send_non_pl31_messages: bool = False,
    ):
        """Init."""
        self.proxy = proxy
        self.name = name
        self.host = host
        self.port = port
        self.cb_data_received = data_received_callback
        self.parent_connection_id = parent_connection_id
        self.run_watchdog = run_watchdog
        self.send_non_pl31_messages = send_non_pl31_messages

        self.watchdog: Watchdog = None

        self.last_received_message: dt.datetime = dt.datetime.now()
        self.last_sent_message: dt.datetime = None

        self.protocol = None
        self.transport: asyncio.Transport = None
        self.connected: bool = False
        self.connection_in_progress: bool = False

        self.ready_to_send: bool = True

        self.unsubscribe_listeners: list[Callable] = []

    async def connect(self):
        """Initiate connection to host."""

        log_message(
            "Request connection for %s %s",
            self.name,
            self.parent_connection_id,
            level=5,
        )

        self.connection_in_progress = True

        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_connection(
            lambda: ConnectionProtocol(
                self.name,
                self.connection_made,
                self.disconnected,
                self.data_received,
            ),
            self.host,
            self.port,
            family=AF_INET,
        )

    def connection_made(self, transport: asyncio.Transport):
        """Handle connection made callback."""
        log_message(
            "Connected to %s server on port %s for %s",
            self.name,
            self.port,
            self.parent_connection_id,
            level=2,
        )

        # Get ref to transport for writing
        self.transport = transport
        self.connected = True

        # Start watchdog timer
        if self.run_watchdog:
            self.watchdog = Watchdog(self.proxy, self.name, 120)
            self.watchdog.start()

            self.unsubscribe_listeners.extend(
                [
                    # listen for watchdog events
                    self.proxy.events.subscribe(
                        self.name,
                        EventType.REQUEST_DISCONNECT,
                        self.handle_disconnect_event,
                    ),
                ]
            )

        # Fire connected event
        # Fire connected event
        self.proxy.events.fire_event(
            Event(
                name=self.name,
                event_type=EventType.CONNECTION,
                client_id=self.parent_connection_id,
                event_data={
                    "connection": self,
                    "send_non_pl31_messages": self.send_non_pl31_messages,
                },
            )
        )

    def data_received(self, _: asyncio.Transport, data: bytes):
        """Handle data received callback."""
        # Show divider if level 4 loggin or above
        log_message("".rjust(60, "-"), level=4)
        log_message(
            "Received Data: %s %s - %s",
            self.name,
            self.parent_connection_id,
            data,
            level=6,
        )

        self.last_received_message = dt.datetime.now()

        if self.cb_data_received:
            self.cb_data_received(self.name, self.parent_connection_id, data)

    async def send_message(self, queued_message: QueuedMessage):
        """Send message."""
        # Check client is connected
        if self.connected:
            try:
                if self.send_non_pl31_messages:
                    self.transport.write(queued_message.message.data)
                    log_message("Data Sent: %s", queued_message.message.data, level=6)
                else:
                    self.transport.write(queued_message.message.raw_data)
                    log_message(
                        "Data Sent: %s", queued_message.message.raw_data, level=6
                    )

                self.last_sent_message = dt.datetime.now()

                log_message(
                    "%s->%s %s - %s %s %s",
                    queued_message.source,
                    self.name,
                    queued_message.destination_client_id,
                    f"{queued_message.message.msg_id:0>4}",
                    queued_message.message.msg_type,
                    queued_message.message.data.hex(" "),
                    level=3 if queued_message.message.msg_type == VIS_ACK else 2,
                )

            except Exception as ex:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                _LOGGER.error(
                    "Exception occured sending message to %s - %s. %s\n%s",
                    self.name,
                    self.parent_connection_id,
                    ex,
                    traceback.format_exc(),
                )
            else:
                return True

    async def handle_disconnect_event(self, event: Event):
        """Handle disconnect event."""
        if event.name == self.name:
            await self.shutdown()

    def disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        self.connected = False
        log_message(
            "%s %s server has disconnected",
            self.name,
            self.parent_connection_id,
            level=1,
        )
        if transport:
            transport.close()
        # Fire connected event
        self.proxy.events.fire_event(
            Event(
                name=self.name,
                event_type=EventType.DISCONNECTION,
                client_id=self.parent_connection_id,
            )
        )

    async def shutdown(self):
        """Disconnect from Server."""
        log_message(
            "Shutting down connection to %s %s",
            self.name,
            self.parent_connection_id,
            level=6,
        )

        # Unsubscribe listeners
        if self.unsubscribe_listeners:
            for unsub in self.unsubscribe_listeners:
                unsub()

        # Stop watchdog
        if self.watchdog:
            await self.watchdog.stop()

        self.connected = False
        if self.transport:
            if self.transport.can_write_eof():
                self.transport.write_eof()
            self.transport.close()