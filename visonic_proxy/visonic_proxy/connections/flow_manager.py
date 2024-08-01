"""Handles flow control."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import itertools
import logging
import re
import traceback

from ..builder import MessageBuilder, NonPowerLink31Message
from ..const import (
    ACK_TIMEOUT,
    ADM_ACK,
    ALARM_MONITOR_SENDS_ACKS,
    NAK,
    PROXY_MODE,
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
    ConnectionSourcePriority,
    ConnectionStatus,
)
from ..decoders.pl31_decoder import PowerLink31Message, PowerLink31MessageDecoder
from ..events import (
    Event,
    EventType,
    async_fire_event,
    async_fire_event_later,
    fire_event,
    subscribe,
)
from ..helpers import get_connection_id, log_message
from ..message_tracker import MessageTracker
from .message import QueuedMessage

_LOGGER = logging.getLogger(__name__)


@dataclass
class WaitingAck:
    """Class to hold waiting ack info."""

    name: ConnectionName
    client_id: str
    msg_id: int


class QID:
    """Hold queue id."""

    id_iter = itertools.count()

    @staticmethod
    def get_next():
        """Get next queue_id."""
        return next(QID.id_iter)


@dataclass
class ConnectionInfo:
    """Store connection info."""

    status: ConnectionStatus
    connection_priority: int
    requires_ack: bool
    send_non_pl31_messages: bool
    last_received: dt.datetime = None
    last_sent: dt.datetime = None


class FlowManager:
    """Manages message flow.

    Only allows send message to 1 connection at a time and waiting
    for an ACK (and return message?) before continuing.

    Will wait until no messages for 0.x seconds before allowing a Monitor injected message
    """

    def __init__(
        self, send_message_callback: Callable, connection_ready_callback: Callable
    ):
        """Initialise."""

        self.cb_send_message = send_message_callback
        self.cb_connection_ready = connection_ready_callback

        self.connection_info: dict[str, ConnectionInfo] = {}
        self.connections = []

        self.sender_queue = asyncio.PriorityQueue()
        self.rts = asyncio.Event()
        self.pending_has_connected = asyncio.Event()

        self.rts.set()
        self.pending_has_connected.set()

        self.ack_awaiter: WaitingAck = None

        # Start message queue processor
        loop = asyncio.get_running_loop()
        self.message_sender_task = loop.create_task(
            self._queue_processor(), name="Flow Manager Send Queue Processor"
        )
        # Subscribe to ack timeout events
        subscribe("ALL", EventType.ACK_TIMEOUT, self.ack_timeout)

    async def shutdown(self):
        """Shutdown flow manager."""
        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()
            await asyncio.sleep(0)

    def _get_connection_info(
        self, name: ConnectionName, client_id: str
    ) -> tuple[str, ConnectionInfo | None]:
        """Return connection info entry."""
        connection_id = get_connection_id(name, client_id)
        return connection_id, self.connection_info.get(connection_id)

    def register_connection(
        self,
        name: ConnectionName,
        client_id: str,
        connection_status: ConnectionStatus,
        connection_priority: int = 1,
        requires_ack: bool = True,
        send_non_pl31_messages: bool = False,
    ):
        """Register a connection to manage within flow manager."""
        connection_id = get_connection_id(name, client_id)

        # We hold the queue if trying to process a message destined for a pending
        # connection.  If that connection connects, release the send queue.
        if (
            connection_id in self.connection_info
            and self.connection_info[connection_id].status
            == ConnectionStatus.CONNECTING
            and connection_status == ConnectionStatus.CONNECTED
        ):
            self.pending_has_connected.set()

        self.connection_info[connection_id] = ConnectionInfo(
            status=connection_status,
            connection_priority=connection_priority,
            requires_ack=requires_ack,
            send_non_pl31_messages=send_non_pl31_messages,
        )
        log_message(
            "%s %s registered with flow manager as %s",
            name,
            client_id,
            connection_status.name,
            level=5,
        )

    def unregister_connection(self, name: ConnectionName, client_id: str):
        """Unregister connection from flow manager."""
        connection_id, connection_info = self._get_connection_info(name, client_id)
        if connection_info:
            del self.connection_info[connection_id]
            log_message(
                "%s %s unregistered with flow manager", name, client_id, level=5
            )

    def data_received(self, source: ConnectionName, client_id: str, data: bytes):
        """Handle callback for when data received on a connection."""

        # Needs to receive source and data.
        # Will decode message into PowerLink31 message structure
        # Filtering should go here
        # Decide if to pass to router
        # Update last received for connection in conneciton info - helps sender decide when to send
        # Know if in connected or disconnected mode
        # Fire event to send to router and other interested parties (like watchdog)
        log_message("%s %s -> %s", source, client_id, data, level=4)
        connection_id, connection_info = self._get_connection_info(source, client_id)

        if not connection_info:
            # This connection is not being managed by flow manager.
            # Do nothing
            return

        # Update client last received
        self.connection_info[connection_id].last_received = dt.datetime.now()

        # Filter messages to ignore

        decoded_messages: list[PowerLink31Message | NonPowerLink31Message] = []

        if connection_info.send_non_pl31_messages:
            # Convert to a PL31 message
            decoded_messages.append(MessageBuilder().message_preprocessor(data))
            # _LOGGER.info("DECODED MSGS: %s", decoded_messages)

        else:
            # It is possible that some messages are multiple messages combined.
            # Need to split them, process each
            # in turn and fire DATA RECEIVED message for each.
            split_after = ["5d 0d"]
            rx = re.compile(rf'(?<=({"|".join(split_after)}))[^\b]')
            messages = [x for x in rx.split(data.hex(" ")) if x not in split_after]

            for message in messages:
                # Decode PL31 message wrapper
                # Decode powerlink 31 wrapper
                decoded_messages = [
                    PowerLink31MessageDecoder().decode_powerlink31_message(
                        bytes.fromhex(message)
                    )
                    for message in messages
                ]

        # Now log and raise events for each message
        destination = None
        destination_client_id = None
        for decoded_message in decoded_messages:
            # _LOGGER.info("DECODED MSG: %s", decoded_message)
            log_message(
                "%s %s-%s-> %s %s",
                source,
                client_id,
                decoded_message.msg_id,
                decoded_message.msg_type,
                decoded_message.data.hex(" "),
                level=3,
            )

            # If waiting ack and receive ack, set RTS
            # TODO: Is this logic right?
            if not self.is_rts and decoded_message.msg_type in [VIS_ACK, ADM_ACK, NAK]:
                self.release_send_queue()

                if self.ack_awaiter and (
                    int(decoded_message.msg_id) == int(self.ack_awaiter.msg_id)
                    or int(decoded_message.msg_id) == int(self.ack_awaiter.msg_id) + 1
                    or (int(decoded_message.msg_id) == 0 and not PROXY_MODE)
                ):
                    # If we were awaitng a specific ACK, add the waiter info to the event
                    # Sometimes Alarm sends a higher msg id in the ACK, accept a +1 tolerance
                    destination = self.ack_awaiter.name
                    destination_client_id = self.ack_awaiter.client_id

                    if decoded_message.msg_id == 0:
                        # Assume this is for us if not in Proxy Mode
                        decoded_message.msg_id = self.ack_awaiter.msg_id

                    log_message(
                        "Waited ACK received: %s -> %s",
                        decoded_message.msg_id,
                        self.ack_awaiter.name,
                        level=4,
                    )
                    # Reset awaiting ack
                    self.ack_awaiter = None

            # Send message to listeners
            fire_event(
                Event(
                    name=source,
                    event_type=EventType.DATA_RECEIVED,
                    client_id=client_id,
                    event_data=decoded_message,
                    destination=destination,
                    destination_client_id=destination_client_id,
                )
            )

    async def queue_message(
        self,
        source: ConnectionName,
        source_client_id: str,
        destination: ConnectionName,
        destination_client_id: str,
        message: PowerLink31Message | NonPowerLink31Message,
        requires_ack: bool = True,
    ):
        """Add message to send queue for processing."""

        priority = ConnectionSourcePriority[source.name]

        queue_entry = QueuedMessage(
            QID.get_next(),
            source,
            source_client_id,
            destination,
            destination_client_id,
            message,
            requires_ack,
        )
        await self.sender_queue.put((priority, queue_entry))
        return True

    async def _queue_processor(self):
        """Process send queue."""
        while True:
            queue_message = await self.sender_queue.get()

            # Wait until RTS
            await self.rts.wait()

            message: QueuedMessage = queue_message[1]

            connection_id, connection_info = self._get_connection_info(
                message.destination, message.destination_client_id
            )

            if connection_info:
                # Here we wait if the message is destined for a pending connection until
                # it has connected.
                if connection_info.status == ConnectionStatus.CONNECTING:
                    self.pending_has_connected.clear()

                # Wait for the pending connection.  If it is not a pending connection, this will
                # just continuie.
                await self.pending_has_connected.wait()

                msg_id = await self._send_message(message)

                # TODO: Move this decision into the router.py
                # Set some overides here for known messages that do not get ACKd
                if (
                    message.destination == ConnectionName.ALARM_MONITOR
                    and not ALARM_MONITOR_SENDS_ACKS
                ):
                    message.requires_ack = False

                if message.message.msg_type == VIS_BBA and message.requires_ack:
                    # Hold which connection requires the ACK we receive
                    self.ack_awaiter = WaitingAck(
                        message.source, message.source_client_id, msg_id
                    )
                    log_message("Awaiting ACK: %s", self.ack_awaiter, level=4)

                # Send message to listeners
                await async_fire_event(
                    Event(
                        message.destination,
                        EventType.DATA_SENT,
                        message.destination_client_id,
                        message.message.data,
                    )
                )

                if (
                    message.message.msg_type not in [VIS_ACK, ADM_ACK]
                    and message.requires_ack
                    and connection_info.requires_ack
                ):
                    await self.wait_for_ack(
                        message.destination, message.destination_client_id, msg_id
                    )

            # Message done even if not sent due to no clients
            self.sender_queue.task_done()

    async def _send_message(self, queued_message: QueuedMessage) -> int | None:
        """Send message.

        return message id for ack tracker
        """
        if self.cb_send_message:
            try:
                if isinstance(queued_message.message, NonPowerLink31Message):
                    # Need to build powerlink message before we send
                    if (
                        msg_id := queued_message.message.msg_id == 0
                        and queued_message.destination != ConnectionName.ALARM_MONITOR
                    ):
                        msg_id = MessageTracker.get_next()

                    queued_message.message = MessageBuilder().build_powerlink31_message(
                        msg_id,
                        queued_message.message.data,
                        queued_message.message.msg_type == VIS_ACK,
                    )
                await self.cb_send_message(queued_message)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.error(
                    "Error sending message to connection manager.  Error is: %s\n%s",
                    ex,
                    traceback.format_exc(),
                )
            else:
                return queued_message.message.msg_id

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

    async def wait_for_ack(self, name: ConnectionName, client_id: str, message_id: int):
        """Wait for ack notification."""
        # Called to set wait
        log_message("%s %s-%s waiting for ACK", name, client_id, message_id, level=5)
        self.hold_send_queue()

        # Create timeout event
        timeout = await async_fire_event_later(
            ACK_TIMEOUT,
            Event(name, EventType.ACK_TIMEOUT, client_id),
        )
        await self.rts.wait()
        timeout.cancel()

    async def ack_timeout(self, event: Event):
        """ACK timeout callback."""

        _LOGGER.warning("Timeout waiting for ACK from %s", event.name)
        self.release_send_queue()
