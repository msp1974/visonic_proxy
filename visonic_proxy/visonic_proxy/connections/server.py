"""Handles listening ports for clients to connect to."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import logging
from socket import AF_INET

from ..const import KEEPALIVE_TIMER, VIS_ACK, ConnectionName
from ..events import Event, EventType, async_fire_event, fire_event, subscribe
from ..helpers import log_message
from .message import QueuedMessage
from .protocol import ConnectionProtocol
from .watchdog import Watchdog

_LOGGER = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """Class to hold client connections."""

    transport: asyncio.Transport
    last_received_message: dt.datetime = None
    hold_sending: bool = False


class ServerConnection:
    """Handles Alarm device connection.

    Uses events to notify of connection, disconnection
    """

    def __init__(
        self,
        name: ConnectionName,
        host: str,
        port: int,
        data_received_callback: Callable | None = None,
        run_keepalive: bool = False,
        run_watchdog: bool = False,
        send_non_pl31_messages: bool = False,
    ):
        """Init."""
        self.name = name
        self.host = host
        self.port = port
        self.cb_data_received = data_received_callback
        self.run_keepalive = run_keepalive
        self.run_watchdog = run_watchdog
        self.send_non_pl31_messages = send_non_pl31_messages

        self.server: asyncio.Server = None
        self.keep_alive_timer_task: asyncio.Task = None
        self.watchdog: Watchdog = None

        self.clients: dict[str, ClientConnection] = {}

        self.disconnected_mode: bool = True
        self.disable_acks: bool = False

        self.unsubscribe_listeners: list[Callable] = []

    @property
    def client_count(self):
        """Get count of clients."""
        return len(self.clients)

    def get_client_id(self, transport: asyncio.Transport) -> str:
        """Generate client_id."""
        return f"P{transport.get_extra_info('peername')[1]}"
        # return f"C{self.client_count + 1}"

    def get_first_client_id(self):
        """Get first connected client id."""
        if self.clients:
            return next(iter(self.clients))

    async def start_listening(self):
        """Start server to allow Alarm to connect."""
        try:
            loop = asyncio.get_running_loop()
            self.server = await loop.create_server(
                lambda: ConnectionProtocol(
                    self.name,
                    self.client_connected,
                    self.client_disconnected,
                    self.data_received,
                ),
                self.host,
                self.port,
                family=AF_INET,
            )
            log_message(
                "Listening for %s connection on %s port %s",
                self.name,
                self.host,
                self.port,
                level=1,
            )

            # Start watchdog timer
            if self.run_watchdog:
                self.watchdog = Watchdog(self.name, 120)
                self.watchdog.start()

                # listen for watchdog events
                self.unsubscribe_listeners.extend(
                    [
                        subscribe(
                            self.name,
                            EventType.REQUEST_DISCONNECT,
                            self.handle_disconnect_event,
                        ),
                    ]
                )
        except OSError as ex:
            _LOGGER.error("Unable to start %s server. Error is %s", self.name, ex)

    def client_connected(self, transport: asyncio.Transport):
        """Handle connection callback."""

        # Add client to clients tracker
        client_id = self.get_client_id(transport)
        self.clients[client_id] = ClientConnection(transport, dt.datetime.now())

        log_message(
            "Client connected to %s %s server. Clients: %s",
            self.name,
            client_id,
            len(self.clients),
            level=1,
        )
        _LOGGER.debug("Connections: %s", self.clients)

        # Fire connected event
        fire_event(
            Event(
                name=self.name,
                event_type=EventType.CONNECTION,
                client_id=client_id,
                event_data={"send_non_pl31_messages": self.send_non_pl31_messages},
            )
        )

        # If needs keepalive timer, start it
        if self.run_keepalive and not self.keep_alive_timer_task:
            loop = asyncio.get_running_loop()
            self.keep_alive_timer_task = loop.create_task(
                self.keep_alive_timer(), name="KeepAlive timer"
            )

            log_message("Started KeepAlive Timer", level=1)

    def data_received(self, transport: asyncio.Transport, data: bytes):
        """Handle callback for when data received."""

        client_id = self.get_client_id(transport)
        # _LOGGER.info("%s %s -> %s", self.name, client_id, data)

        # Update client last received
        self.clients[client_id].last_received_message = dt.datetime.now()

        if self.cb_data_received:
            self.cb_data_received(self.name, client_id, data)

    async def send_message(self, queued_message: QueuedMessage):
        """Send message."""
        # Check client is connected
        if queued_message.destination_client_id in self.clients:
            client = self.clients[queued_message.destination_client_id]

            if client.transport:
                if self.send_non_pl31_messages:
                    client.transport.write(queued_message.message.data)
                    log_message("DATA SENT: %s", queued_message.message.data, level=6)
                else:
                    client.transport.write(queued_message.message.raw_data)
                    log_message(
                        "DATA SENT: %s", queued_message.message.raw_data, level=6
                    )

                log_message(
                    "%s->%s %s-%s %s %s",
                    queued_message.source,
                    self.name,
                    queued_message.destination_client_id,
                    f"{queued_message.message.msg_id:0>4}",
                    queued_message.message.msg_type,
                    queued_message.message.data.hex(" "),
                    level=2 if queued_message.message.msg_type == VIS_ACK else 1,
                )
                # Send message to listeners
                await async_fire_event(
                    Event(
                        name=self.name,
                        event_type=EventType.DATA_SENT,
                        client_id=queued_message.destination_client_id,
                        event_data=queued_message.message,
                    )
                )
                return True
        _LOGGER.error(
            "Unable to send message to %s %s",
            queued_message.destination,
            queued_message.destination_client_id,
        )

    def client_disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        client_id = self.get_client_id(transport)
        log_message("Client disconnected from %s %s", self.name, client_id, level=1)

        # Remove client id from list of clients
        try:
            del self.clients[client_id]
        except KeyError:
            _LOGGER.error(
                "Client does not exist trying to remove client form client list"
            )

        _LOGGER.debug("Clients remaining: %s. %s", len(self.clients), self.clients)

        # If has keepalive timer, stop it if no more clients
        if len(self.clients) == 0:
            if self.keep_alive_timer_task and not self.keep_alive_timer_task.done():
                log_message(
                    "Stopping keepalive timer for %s due to no connections",
                    self.name,
                    level=1,
                )
                self.keep_alive_timer_task.cancel()
                self.keep_alive_timer_task = None

        # Send message to listeners
        fire_event(
            Event(
                name=self.name, event_type=EventType.DISCONNECTION, client_id=client_id
            )
        )

    def handle_disconnect_event(self, event: Event):
        """Handle disconnect event."""
        if event.name == self.name:
            self.disconnect_client(event.client_id)

    def disconnect_client(self, client_id: str):
        """Disconnect client."""
        try:
            client = self.clients[client_id]
            if client.transport:
                if client.transport.can_write_eof():
                    client.transport.write_eof()
                client.transport.close()
        except KeyError:
            pass

    async def shutdown(self):
        """Disconect the server."""

        # Unsubscribe listeners
        if self.unsubscribe_listeners:
            for unsub in self.unsubscribe_listeners:
                unsub()

        # Stop keep alive timer
        if self.keep_alive_timer_task and not self.keep_alive_timer_task.done():
            log_message("Stopping keepalive timer for %s", self.name, level=1)
            self.keep_alive_timer_task.cancel()
            while not self.keep_alive_timer_task.done():
                await asyncio.sleep(0.01)

        # Stop watchdog
        if self.watchdog:
            await self.watchdog.stop()

        for client_id in self.clients:
            log_message("Disconnecting from %s %s", self.name, client_id, level=1)
            self.disconnect_client(client_id)

        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def keep_alive_timer(self):
        """Keep alive timer.

        To be run in a task
        """

        while True:
            await asyncio.sleep(1)
            if self.disconnected_mode:
                for client_id, client in self.clients.items():
                    if (
                        client.last_received_message
                        and (
                            dt.datetime.now() - client.last_received_message
                        ).total_seconds()
                        > KEEPALIVE_TIMER
                    ):
                        fire_event(
                            Event(self.name, EventType.SEND_KEEPALIVE, client_id)
                        )
                        await asyncio.sleep(5)
