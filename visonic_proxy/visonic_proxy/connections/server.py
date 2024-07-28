"""Handles listening ports for clients to connect to."""

import asyncio
from dataclasses import dataclass
import datetime as dt
import logging
from socket import AF_INET

from ..const import KEEPALIVE_TIMER, ConnectionName
from ..events import Event, EventType, async_fire_event, fire_event, subscribe
from .protocol import ConnectionProtocol
from .watchdog import Watchdog

_LOGGER = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """Queued message."""

    client_id: str | None = None
    message_id: int = 0
    data: bytes = None
    requires_ack: bool = True

    def __gt__(self, other):
        """Greater than."""
        return self.message_id > other.message_id

    def __lt__(self, other):
        """Less than."""
        return self.message_id < other.message_id


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
        run_keepalive: bool = False,
        run_watchdog: bool = False,
    ):
        """Init."""
        self.name = name
        self.host = host
        self.port = port
        self.run_keepalive = run_keepalive
        self.run_watchdog = run_watchdog

        self.server: asyncio.Server = None
        self.sender_queue = asyncio.PriorityQueue(maxsize=100)

        self.message_sender_task: asyncio.Task = None
        self.keep_alive_timer_task: asyncio.Task = None
        self.watchdog: Watchdog = None

        self.clients: dict[str, ClientConnection] = {}

        self.disconnected_mode: bool = True

    @property
    def client_count(self):
        """Get count of clients."""
        return len(self.clients.keys())

    def get_client_id(self, transport: asyncio.Transport) -> str:
        """Generate client_id."""
        return f"P{transport.get_extra_info('peername')[1]}"

    def get_first_client_id(self):
        """Get first connected client id."""
        if self.clients:
            return next(iter(self.clients))

    async def start_listening(self):
        """Start server to allow Alarm to connect."""
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
        _LOGGER.info(
            "Listening for %s connection on %s port %s", self.name, self.host, self.port
        )

        # Start watchdog timer
        if self.run_watchdog:
            self.watchdog = Watchdog(self.name, 120)
            self.watchdog.start()

            # listen for watchdog events
            subscribe(
                self.name, EventType.REQUEST_DISCONNECT, self.handle_disconnect_event
            )

        # Start message queue processor
        self.message_sender_task = loop.create_task(
            self.send_queue_processor(), name=f"{self.name} Send Queue Processor"
        )

    def client_connected(self, transport: asyncio.Transport):
        """Handle connection callback."""

        # Add client to clients tracker
        client_id = self.get_client_id(transport)
        self.clients[client_id] = ClientConnection(transport, dt.datetime.now())

        _LOGGER.info(
            "Client connected to %s %s server. Clients: %s",
            self.name,
            client_id,
            len(self.clients),
        )
        _LOGGER.debug("Connections: %s", self.clients)

        # Fire connected event
        fire_event(Event(self.name, EventType.CONNECTION, client_id))

        # If needs keepalive timer, start it
        if self.run_keepalive and not self.keep_alive_timer_task:
            loop = asyncio.get_running_loop()
            self.keep_alive_timer_task = loop.create_task(
                self.keep_alive_timer(), name="KeepAlive timer"
            )

            _LOGGER.info("Started KeepAlive Timer")

    def data_received(self, transport: asyncio.Transport, data: bytes):
        """Handle callback for when data received."""

        client_id = self.get_client_id(transport)

        # Update client last received
        self.clients[client_id].last_received_message = dt.datetime.now()

        # Send message to listeners
        fire_event(Event(self.name, EventType.DATA_RECEIVED, client_id, data))

    async def queue_message(
        self,
        priority: int,
        client_id: str,
        message_id: int,
        message: bytes,
        requires_ack: bool = True,
    ):
        """Add message to send queue for processing."""

        # Dont add messages to queue if nowhere to send
        if self.clients:
            # Send to first connection if client id not recognised
            # This will be the case for injected commands from monitor
            if client_id not in self.clients:
                client_id = list(self.clients.keys())[0]

            queue_entry = QueuedMessage(client_id, message_id, message, requires_ack)
            await self.sender_queue.put((priority, queue_entry))
            return True

        _LOGGER.warning("No connected clients. Message will be dropped")
        return False

    async def send_queue_processor(self):
        """Process send queue."""
        while True:
            queue_message = await self.sender_queue.get()
            # _LOGGER.info("QUEUED MSG: %s", queue_message)
            message: QueuedMessage = queue_message[1]

            # Check client is connected
            if message.client_id in self.clients:
                client = self.clients[message.client_id]

                if client.transport:
                    client.transport.write(message.data)
                    _LOGGER.info(
                        "Sent message via %s %s connection\n",
                        self.name,
                        message.client_id,
                    )
                    # Send message to listeners
                    await async_fire_event(
                        Event(
                            self.name,
                            EventType.DATA_SENT,
                            message.client_id,
                            message.data,
                        )
                    )

                    if message.requires_ack:
                        pass

            # Message done even if not sent due to no clients
            self.sender_queue.task_done()

    def client_disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        client_id = self.get_client_id(transport)
        _LOGGER.info(
            "Client disconnected from %s %s",
            self.name,
            client_id,
        )

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
                _LOGGER.info(
                    "Stopping keepalive timer for %s due to no connections", self.name
                )
                self.keep_alive_timer_task.cancel()
                self.keep_alive_timer_task = None

        # Send message to listeners
        fire_event(Event(self.name, EventType.DISCONNECTION, client_id))

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

        # Stop message sender processor
        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()

        # Stop keep alive timer
        if self.keep_alive_timer_task and not self.keep_alive_timer_task.done():
            _LOGGER.info("Stopping keepalive timer for %s", self.name)
            self.keep_alive_timer_task.cancel()
            while not self.keep_alive_timer_task.done():
                await asyncio.sleep(0.01)

        # Stop watchdog
        if self.watchdog:
            self.watchdog.stop()

        for client_id in self.clients:
            _LOGGER.info("Disconnecting from %s %s", self.name, client_id)
            self.disconnect_client(client_id)
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
