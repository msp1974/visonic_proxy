"""Client connection class."""

import asyncio
from dataclasses import dataclass
import datetime as dt
import logging
from socket import AF_INET

from ..events import Event, EventType, fire_event, subscribe
from .protocol import ConnectionProtocol
from .watchdog import Watchdog

_LOGGER = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """Queued message."""

    message_id: int = 0
    data: bytes = None
    requires_ack: bool = True

    def __gt__(self, other):
        """Greater than."""
        return self.message_id > other.message_id

    def __lt__(self, other):
        """Less than."""
        return self.message_id < other.message_id


class ClientConnection:
    """Handles connection to visonic."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        parent_connection_id: str,
        run_watchdog: bool = False,
    ):
        """Init."""
        self.name = name
        self.host = host
        self.port = port
        self.parent_connection_id = parent_connection_id
        self.run_watchdog = run_watchdog

        self.watchdog: Watchdog = None

        self.last_received_message: dt.datetime = dt.datetime.now()
        self.last_sent_message: dt.datetime = None

        self.protocol = None
        self.transport: asyncio.Transport = None
        self.connected: bool = False
        self.connection_in_progress: bool = False

        self.sender_queue = asyncio.PriorityQueue(maxsize=100)
        self.message_sender_task: asyncio.Task = None

        self.ready_to_send: bool = True

    async def connect(self):
        """Initiate connection to host."""

        _LOGGER.info(
            "Initiating connection to %s on behalf of %s",
            self.name,
            self.parent_connection_id,
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
        _LOGGER.info(
            "Connected to %s server on port %s for %s",
            self.name,
            self.port,
            self.parent_connection_id,
        )

        # Get ref to transport for writing
        self.transport = transport
        self.connected = True

        # Start watchdog timer
        if self.run_watchdog:
            self.watchdog = Watchdog(self.name, 120)
            self.watchdog.start()

            # listen for watchdog events
            subscribe(
                self.name, EventType.REQUEST_DISCONNECT, self.handle_disconnect_event
            )

        # Fire connected event
        fire_event(Event(self.name, EventType.CONNECTION, self.parent_connection_id))

        # Start message queue processor
        loop = asyncio.get_running_loop()
        self.message_sender_task = loop.create_task(
            self.send_queue_processor(), name=f"{self.name} Send Queue Processor"
        )

    def data_received(self, _: asyncio.Transport, data: bytes):
        """Handle data received callback."""

        self.last_received_message = dt.datetime.now()

        # Fire data received event
        fire_event(
            Event(self.name, EventType.DATA_RECEIVED, self.parent_connection_id, data)
        )

    async def queue_message(
        self, priority: int, message_id: int, message: bytes, requires_ack: bool = True
    ):
        """Add message to send queue for processing."""

        # Dont add messages to queue if nowhere to send
        if self.connected or self.connection_in_progress:
            queue_entry = QueuedMessage(message_id, message, requires_ack)
            await self.sender_queue.put((priority, queue_entry))
            return True

        _LOGGER.warning("No connected to a server. Message will be dropped")
        return False

    async def send_queue_processor(self):
        """Process send queue."""
        while True:
            queue_message = await self.sender_queue.get()
            # _LOGGER.info("QUEUED MSG: %s", queue_message)
            message: QueuedMessage = queue_message[1]

            # Check client is connected
            if self.connected:
                try:
                    self.transport.write(message.data)
                    self.last_sent_message = dt.datetime.now()
                    _LOGGER.info(
                        "Sent message via %s %s connection\n",
                        self.name,
                        self.parent_connection_id,
                    )
                    # Send message to listeners
                    fire_event(
                        Event(
                            self.name,
                            EventType.DATA_SENT,
                            self.parent_connection_id,
                            message.data,
                        )
                    )

                    if message.requires_ack:
                        pass
                except Exception as ex:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                    _LOGGER.error(
                        "Exception occured sending message to %s - %s. %s",
                        self.name,
                        self.parent_connection_id,
                        ex,
                    )
            # Message done even if not sent due to no connection
            self.sender_queue.task_done()

    def handle_disconnect_event(self, event: Event):
        """Handle disconnect event."""
        if event.name == self.name:
            self.shutdown()

    def disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        self.connected = False
        _LOGGER.info(
            "%s %s server has disconnected", self.name, self.parent_connection_id
        )
        if transport:
            transport.close()
        # Fire connected event
        fire_event(Event(self.name, EventType.DISCONNECTION, self.parent_connection_id))

    async def shutdown(self):
        """Disconnect from Server."""
        _LOGGER.info(
            "Shutting down connection to %s for %s",
            self.name,
            self.parent_connection_id,
        )

        # Stop message sender processor
        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()

        # Stop watchdog
        if self.watchdog:
            self.watchdog.stop()

        self.connected = False
        if self.transport:
            if self.transport.can_write_eof():
                self.transport.write_eof()
            self.transport.close()
