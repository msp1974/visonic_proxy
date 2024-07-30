"""Client connection class."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import logging
import re
from socket import AF_INET

from ..const import ACK_TIMEOUT, VIS_ACK, ConnectionName, ConnectionSourcePriority
from ..decoders.pl31_decoder import PowerLink31MessageDecoder
from ..events import Event, EventType, async_fire_event_later, fire_event, subscribe
from ..helpers import log_message
from .protocol import ConnectionProtocol
from .watchdog import Watchdog

_LOGGER = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """Queued message."""

    source: str
    client_id: str
    message_id: int
    message: str
    data: bytes
    is_ack: bool = False
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
        self.rts = asyncio.Event()

        self.ready_to_send: bool = True

        self.unsubscribe_listeners: list[Callable] = []

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

            self.unsubscribe_listeners.extend(
                [
                    # listen for watchdog events
                    subscribe(
                        self.name,
                        EventType.REQUEST_DISCONNECT,
                        self.handle_disconnect_event,
                    ),
                    # Subscribe to ack timeout events
                    subscribe(self.name, EventType.ACK_TIMEOUT, self.ack_timeout),
                ]
            )

        # Fire connected event
        fire_event(Event(self.name, EventType.CONNECTION, self.parent_connection_id))

        # Start message queue processor
        loop = asyncio.get_running_loop()
        self.message_sender_task = loop.create_task(
            self.send_queue_processor(), name=f"{self.name} Send Queue Processor"
        )

        # Set connection RTS
        self.release_send_queue()

    def data_received(self, _: asyncio.Transport, data: bytes):
        """Handle data received callback."""

        self.last_received_message = dt.datetime.now()

        # It is possible that some messages are multiple messages combined.
        # Only way I can think to handle this is to split them, process each
        # in turn and fire DATA RECEIVED message for each.
        split_after = ["5d 0d"]
        rx = re.compile(rf'(?<=({"|".join(split_after)}))[^\b]')
        messages = [x for x in rx.split(data.hex(" ")) if x not in split_after]

        for message in messages:
            # Decode PL31 message wrapper
            # Decode powerlink 31 wrapper
            pl31_message = PowerLink31MessageDecoder().decode_powerlink31_message(
                bytes.fromhex(message)
            )

            # TODO: Capture this info to fix issue in PL31 decoder
            if pl31_message.msg_id == "00R0":
                _LOGGER.error("NAK: %s", data)

            if pl31_message.type == VIS_ACK:
                log_message(
                    "%s %s-%s-> %s %s",
                    self.name,
                    self.parent_connection_id,
                    pl31_message.msg_id,
                    "ACK",
                    pl31_message.message.hex(" "),
                    level=5,
                )
            else:
                log_message(
                    "%s %s-%s-> %s %s",
                    self.name,
                    self.parent_connection_id,
                    pl31_message.msg_id,
                    "MSG",
                    pl31_message.message.hex(" "),
                    level=2,
                )

            # If waiting ack and receive ack, set RTS
            if not self.is_rts and pl31_message.type == VIS_ACK:
                log_message(
                    "%s %s-%s received ACK",
                    self.name,
                    self.parent_connection_id,
                    pl31_message.msg_id,
                    level=5,
                )
                self.release_send_queue()

            # Fire data received event
            fire_event(
                Event(
                    self.name,
                    EventType.DATA_RECEIVED,
                    self.parent_connection_id,
                    pl31_message,
                )
            )

    async def queue_message(
        self,
        source: ConnectionName,
        client_id: str,
        message_id: int,
        readable_message: str,
        data: bytes,
        is_ack: bool = False,
        requires_ack: bool = True,
    ):
        """Add message to send queue for processing."""

        # Dont add messages to queue if nowhere to send
        if self.connected or self.connection_in_progress:
            priority = ConnectionSourcePriority[source.name]

            queue_entry = QueuedMessage(
                source,
                client_id,
                message_id,
                readable_message,
                data,
                is_ack,
                requires_ack,
            )
            await self.sender_queue.put((priority, queue_entry))

            return True

        _LOGGER.warning("No connected to a server. Message will be dropped")
        return False

    @property
    def is_rts(self):
        """Return if connection ready to send."""
        return self.rts.is_set()

    def hold_send_queue(self):
        """Hold send queue."""
        self.rts.clear()

    def release_send_queue(self):
        """Release send queue."""
        self.rts.set()

    async def send_queue_processor(self):
        """Process send queue."""
        while True:
            queue_message = await self.sender_queue.get()

            # Wait until RTS
            await self.rts.wait()

            message: QueuedMessage = queue_message[1]

            # Check client is connected
            if self.connected:
                try:
                    self.transport.write(message.data)
                    self.last_sent_message = dt.datetime.now()
                    log_message(
                        "%s->%s %s-%s %s %s",
                        message.source,
                        self.name,
                        self.parent_connection_id,
                        message.message_id,
                        "ACK" if message.is_ack else "MSG",
                        message.message,
                        level=3,
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
                        await self.wait_for_ack(message.message_id)
                except Exception as ex:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                    _LOGGER.error(
                        "Exception occured sending message to %s - %s. %s",
                        self.name,
                        self.parent_connection_id,
                        ex,
                    )
            # Message done even if not sent due to no connection
            self.sender_queue.task_done()

    async def wait_for_ack(self, message_id: int):
        """Wait for ack notification."""
        # Called to set wait
        log_message(
            "%s %s-%s waiting for ACK",
            self.name,
            self.parent_connection_id,
            message_id,
            level=5,
        )
        self.hold_send_queue()

        # Create timeout event
        timeout = await async_fire_event_later(
            ACK_TIMEOUT,
            Event(self.name, EventType.ACK_TIMEOUT, self.parent_connection_id),
        )
        await self.rts.wait()
        timeout.cancel()

    async def ack_timeout(self, event: Event):
        """ACK timeout callback."""
        if (
            event.name == self.name
            and event.client_id == self.parent_connection_id
            and event.event_type == EventType.ACK_TIMEOUT
        ):
            log_message(
                "ACK TIMEOUT: %s %s", self.name, self.parent_connection_id, level=5
            )
            self.release_send_queue()

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
        fire_event(Event(self.name, EventType.DISCONNECTION, self.parent_connection_id))

    async def shutdown(self):
        """Disconnect from Server."""
        log_message(
            "Shutting down connection to %s for %s",
            self.name,
            self.parent_connection_id,
            level=1,
        )

        # Unsubscribe listeners
        for unsub in self.unsubscribe_listeners:
            unsub()

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
