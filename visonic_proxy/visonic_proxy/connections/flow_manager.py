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
    DUH,
    NAK,
    VIS_ACK,
    ConnectionName,
    ConnectionSourcePriority,
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
from ..helpers import log_message
from ..message_tracker import MessageTracker
from .message import QueuedMessage

_LOGGER = logging.getLogger(__name__)


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

    connection_priority: int
    requires_ack: bool
    uses_pl31_messages: bool
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

        self.rts.set()

        self.do_not_route_ack: int = None

        # Start message queue processor
        loop = asyncio.get_running_loop()
        self.message_sender_task = loop.create_task(
            self._queue_processor(), name="Flow Manager Send Queue Processor"
        )
        # Subscribe to ack timeout events
        (subscribe("ALL", EventType.ACK_TIMEOUT, self.ack_timeout),)

    async def shutdown(self):
        """Shutdown flow manager."""
        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()
            await asyncio.sleep(0)

    def _get_connection_id(self, name: ConnectionName, client_id: str) -> str:
        """Return connection id."""
        return f"{name}_{client_id}"

    def _get_connection_info(
        self, name: ConnectionName, client_id: str
    ) -> tuple[str, ConnectionInfo | None]:
        """Return connection info entry."""
        connection_id = self._get_connection_id(name, client_id)
        return connection_id, self.connection_info.get(connection_id)

    def register_connection(
        self,
        name: ConnectionName,
        client_id: str,
        connection_priority: int = 1,
        requires_ack: bool = True,
        uses_pl31_messages: bool = True,
    ):
        """Register a connection to manage within flow manager."""
        connection_id = self._get_connection_id(name, client_id)
        self.connection_info[connection_id] = ConnectionInfo(
            connection_priority=connection_priority,
            requires_ack=requires_ack,
            uses_pl31_messages=uses_pl31_messages,
        )
        _LOGGER.info("%s %s registered with flow manager", name, client_id)

    def unregister_connection(self, name: ConnectionName, client_id: str):
        """Unregister connection from flow manager."""
        connection_id, connection_info = self._get_connection_info(name, client_id)
        if connection_info:
            del self.connection_info[connection_id]
            _LOGGER.info("%s %s unregistered with flow manager", name, client_id)

    def data_received(self, source: ConnectionName, client_id: str, data: bytes):
        """Handle callback for when data received on a connection."""

        # Needs to receive source and data.
        # Will decode message into PowerLink31 message structure
        # Filtering should go here
        # Decide if to pass to router
        # Update last received for connection in conneciton info - helps sender decide when to send
        # Know if in connected or disconnected mode
        # Fire event to send to router and other interested parties (like watchdog)
        _LOGGER.info("%s %s -> %s", source, client_id, data)
        connection_id, connection_info = self._get_connection_info(source, client_id)

        if not connection_info:
            # This connection is not being managed by flow manager.
            # Do nothing
            return

        # Update client last received
        self.connection_info[connection_id].last_received = dt.datetime.now()

        decoded_messages: list[PowerLink31Message | NonPowerLink31Message] = []

        if (
            not connection_info.uses_pl31_messages
            or source == ConnectionName.ALARM_MONITOR
        ):
            # Convert to a PL31 message
            decoded_messages.append(MessageBuilder().message_preprocessor(data))

        else:
            # It is possible that some messages are multiple messages combined.
            # Only way I can think to handle this is to split them, process each
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
        for decoded_message in decoded_messages:
            is_pl31 = isinstance(decoded_message, PowerLink31Message)

            if decoded_message.msg_type == [VIS_ACK, ADM_ACK]:
                log_message(
                    "%s %s-%s-> %s %s",
                    source,
                    client_id,
                    decoded_message.msg_id if is_pl31 else 0,
                    "ACK" if decoded_message.msg_type in [VIS_ACK, ADM_ACK] else "NAK",
                    decoded_message.data.hex(" "),
                    level=5,
                )
            else:
                log_message(
                    "%s %s-%s-> %s %s",
                    source,
                    client_id,
                    decoded_message.msg_id if is_pl31 else 0,
                    "MSG",
                    decoded_message.data.hex(" "),
                    level=2,
                )

            # If waiting ack and receive ack, set RTS
            if not self.is_rts and decoded_message.msg_type in [VIS_ACK, ADM_ACK, NAK]:
                log_message(
                    "%s %s-%s received ACK",
                    source,
                    client_id,
                    decoded_message.msg_id if is_pl31 else 0,
                    level=5,
                )
                self.release_send_queue()

                if self.do_not_route_ack and self.do_not_route_ack == int(
                    decoded_message.msg_id
                ):
                    self.do_not_route_ack = None
                    _LOGGER.info("DO NOT PASS ACK RECEIVED: %s", decoded_message.msg_id)
                    return

            # Send message to listeners
            fire_event(
                Event(
                    source,
                    EventType.DATA_RECEIVED,
                    client_id,
                    event_data=decoded_message,
                )
            )

    async def queue_message(
        self,
        source: ConnectionName,
        destination: ConnectionName,
        client_id: str,
        message: PowerLink31Message | NonPowerLink31Message,
        requires_ack: bool = True,
        do_not_route_ack: bool = False,
    ):
        """Add message to send queue for processing."""

        priority = ConnectionSourcePriority[source.name]

        queue_entry = QueuedMessage(
            QID.get_next(),
            source,
            destination,
            client_id,
            message,
            requires_ack,
            do_not_route_ack,
        )
        await self.sender_queue.put((priority, queue_entry))
        return True

        # _LOGGER.warning("No connected clients. Message will be dropped")
        # return False

    async def _queue_processor(self):
        """Process send queue."""
        while True:
            queue_message = await self.sender_queue.get()

            # Wait until RTS
            await self.rts.wait()

            message: QueuedMessage = queue_message[1]

            connection_id, connection_info = self._get_connection_info(
                message.destination, message.client_id
            )

            if connection_info:
                msg_id = await self._send_message(message)

                if message.do_not_route_ack:
                    # Messages from CM will have do not route ack set to ensure we
                    # do not send the ACK to Visonic when it is not expecting it.
                    # Fixes comms failure trouble on app.
                    self.do_not_route_ack = int(msg_id)
                    _LOGGER.info("DO NOT PASS ACK SET TO %s", self.do_not_route_ack)

                # Send message to listeners
                await async_fire_event(
                    Event(
                        message.destination,
                        EventType.DATA_SENT,
                        message.client_id,
                        message.message.data,
                    )
                )

                if (
                    message.message.msg_type not in [VIS_ACK, ADM_ACK, NAK, DUH]
                    and message.requires_ack
                    and connection_info.requires_ack
                    and message.destination != ConnectionName.ALARM_MONITOR
                ):
                    await self.wait_for_ack(
                        message.destination, message.client_id, msg_id
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

        log_message("ACK TIMEOUT: %s", event.name, level=5)
        self.release_send_queue()
