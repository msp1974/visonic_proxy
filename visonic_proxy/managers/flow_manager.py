"""Handles flow control."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import itertools
import logging
import re
import traceback

from ..const import (
    ADM_ACK,
    ADM_CID,
    NAK,
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
    ConnectionStatus,
    MsgLogLevel,
)
from ..events import ALL_CLIENTS, Event, EventType
from ..message import QueuedMessage, QueuedReceivedMessage, RoutableMessage
from ..proxy import Proxy
from ..transcoders.builder import MessageBuilder, NonPowerLink31Message
from ..transcoders.pl31_decoder import PowerLink31Message, PowerLink31MessageDecoder
from .message_router import MessageRouter

_LOGGER = logging.getLogger(__name__)


@dataclass
class WaitingAck:
    """Class to hold waiting ack info."""

    source: ConnectionName
    source_client_id: str
    desination: ConnectionName
    destination_client_id: str
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

    name: ConnectionName
    client_id: int
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

    def __init__(self, proxy: Proxy):
        """Initialise."""

        self.proxy = proxy
        self.cb_send_message: Callable
        self.cb_connection_ready: Callable

        self.connection_info: dict[str, dict[int, ConnectionInfo]] = {}
        self.connections = []

        self.receive_queue = asyncio.PriorityQueue()
        self.sender_queue = asyncio.PriorityQueue()
        self.rts = asyncio.Event()
        self.pending_has_connected = asyncio.Event()

        self.message_receiver_task: asyncio.Task
        self.message_sender_task: asyncio.Task

        self.message_router = MessageRouter(self.proxy)

        self.ack_awaiter: WaitingAck = None

        self._unsubscribe_listeners: list[Callable] = []

    async def start(self, send_message_callback: Callable):
        """Start flow manager."""
        self.cb_send_message = send_message_callback

        await self.message_router.start(self.queue_message)

        # Subscribe to ack timeout events
        self._unsubscribe_listeners = [
            self.proxy.events.subscribe(
                ALL_CLIENTS, EventType.ACK_TIMEOUT, self.ack_timeout
            )
        ]

        # Start message queue processors
        self.message_receiver_task = self.proxy.loop.create_task(
            self._receive_queue_processor(), name="Flow Manager Receive Queue Processor"
        )
        self.message_sender_task = self.proxy.loop.create_task(
            self._send_queue_processor(), name="Flow Manager Send Queue Processor"
        )

        self.rts.set()
        self.pending_has_connected.set()

        _LOGGER.info("Flow Manager started")

    async def stop(self):
        """Shutdown flow manager."""
        await self.message_router.stop()

        for unsub in self._unsubscribe_listeners:
            unsub()

        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()

        if self.message_receiver_task and not self.message_receiver_task.done():
            self.message_receiver_task.cancel()

        _LOGGER.info("Flow Manager stopped")

    def set_panel_data(self, panel_id: str, account_id: str):
        """Set panel data in message builder."""
        if not self.proxy.panel_id:
            self.proxy.panel_id = panel_id
        if not self.proxy.account_id:
            self.proxy.account_id = account_id

    def data_received(
        self, source_name: ConnectionName, source_client_id: str, data: bytes
    ):
        """Receive data and add to receive queue."""

        self.receive_queue.put_nowait(
            (QID.get_next(), QueuedReceivedMessage(source_name, source_client_id, data))
        )
        _LOGGER.debug(
            "Queued Received Data: %s %s %s",
            source_name,
            source_client_id,
            data,
        )

    async def _receive_queue_processor(self):
        """Process receive queue."""
        while True:
            queued_message = await self.receive_queue.get()
            message: QueuedReceivedMessage = queued_message[1]

            source = message.source
            client_id = message.source_client_id
            data = message.data

            _LOGGER.debug("Retrieved from Receive Queue: %s", message)

            connection_info = self.proxy.clients.get_client(source, client_id)

            if not connection_info:
                # This connection is not being managed by flow manager.
                # Do nothing
                _LOGGER.warning(
                    "Flow Manager received from an unregistered connection: %s",
                    message,
                )
                continue

            # Update client last received
            connection_info.last_received = dt.datetime.now()
            self.proxy.clients.update(source, client_id, connection_info)

            # Filter messages to ignore

            decoded_messages: list[PowerLink31Message | NonPowerLink31Message] = []

            if connection_info.send_non_pl31_messages:
                # Convert to a PL31 message
                decoded_messages.append(
                    MessageBuilder(self.proxy).message_preprocessor(data)
                )
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
                _LOGGER.info(
                    "REC << %s %s - %s %s %s",
                    source,
                    client_id,
                    f"{decoded_message.msg_id:0>4}",
                    decoded_message.msg_type,
                    decoded_message.data.hex(" "),
                    extra=MsgLogLevel.L4,
                )
                if source == ConnectionName.ALARM:
                    # Set panel info
                    self.set_panel_data(
                        decoded_message.panel_id, decoded_message.account_id
                    )

                    # Update tracking info
                    try:
                        message_no = decoded_message.msg_id
                        timestamp = dt.datetime.now(dt.UTC)
                        if message_no != 0 and decoded_message.msg_type in [
                            VIS_BBA,
                            VIS_ACK,
                        ]:
                            self.proxy.message_tracker.last_message_no = message_no
                            self.proxy.message_tracker.last_message_timestamp = (
                                timestamp
                            )
                            _LOGGER.debug(
                                "Tracking Info: msg_id: %s, timestamp: %s",
                                message_no,
                                timestamp,
                            )
                    except ValueError:
                        _LOGGER.warning(
                            "Unrecognised message format from %s %s.  Skipping decoding",
                            source,
                            client_id,
                        )
                        _LOGGER.warning("Message: %s", data)
                        _LOGGER.warning("Powerlink: %s", decoded_message)
                        continue

                # EXPERIMENTAL - If waiting ack from a connection and get a message, release ACK wait
                if (
                    self.ack_awaiter
                    and self.ack_awaiter.source == source
                    and self.ack_awaiter.source_client_id == client_id
                    and decoded_message.msg_type in [VIS_BBA, ADM_CID]
                ):
                    _LOGGER.info(
                        "Skip waiting ack from %s as received new message",
                        source,
                        extra=MsgLogLevel.L5,
                    )
                    self.release_send_queue()

                # If waiting ack and receive ack, set RTS
                elif (
                    not self.is_rts  # Waiting for ACK
                    and decoded_message.msg_type
                    in [VIS_ACK, ADM_ACK, NAK]  # And this is an ACK message
                ):
                    # Is it our awaited ACK?
                    if (
                        self.ack_awaiter
                        and source == self.ack_awaiter.source
                        and client_id == self.ack_awaiter.source_client_id
                        and (
                            (
                                # Only match msg id if MATCH_ACK_MSG_ID is true - EXPERIMENTAL
                                decoded_message.msg_id == self.ack_awaiter.msg_id
                                or not self.proxy.config.MATCH_ACK_MSG_ID
                            )
                            or (
                                # Sometimes Visonic gets out of sync and Alarm sends ACK 1 higher than Visonic waiting for
                                source == ConnectionName.ALARM
                                and self.ack_awaiter.desination
                                == ConnectionName.VISONIC
                                and decoded_message.msg_id > self.ack_awaiter.msg_id
                            )
                            or (
                                # ACKs comming from the Alarm Monitor are not Powerlink messages and therefore have no message id
                                # This overcomes that
                                source == ConnectionName.ALARM_MONITOR
                                and self.ack_awaiter.desination == ConnectionName.ALARM
                                and decoded_message.msg_id == 0
                            )
                            or (
                                # Sometimes HA sent messages get out of sync and Alarm sends ACK 1 higher than HA waiting for
                                source == ConnectionName.ALARM
                                and self.ack_awaiter.desination
                                == ConnectionName.ALARM_MONITOR
                                and decoded_message.msg_id > self.ack_awaiter.msg_id
                            )
                        )
                    ):
                        # Set the destination info for the DATA RECEIVED event
                        # So the router knows where to forward it to
                        destination = self.ack_awaiter.desination
                        destination_client_id = self.ack_awaiter.destination_client_id

                        _LOGGER.info(
                            "Received awaited ACK for %s %s from %s %s for msg id %s",
                            self.ack_awaiter.desination,
                            self.ack_awaiter.destination_client_id,
                            source,
                            client_id,
                            decoded_message.msg_id,
                            extra=MsgLogLevel.L5,
                        )
                        # If ACK and Waiter out of sync, log message
                        # This is accepted above if 1 out
                        # It is expected that ACKs from Alarm Monitor will have a message id of 0 as non powerlink message
                        # so dont log if that is the case
                        if decoded_message.msg_id != self.ack_awaiter.msg_id and not (
                            source == ConnectionName.ALARM_MONITOR
                            and decoded_message.msg_id == 0
                        ):
                            _LOGGER.info(
                                "ACK was out of sync with awaiter. ACK: %s, WAITER: %s",
                                decoded_message.msg_id,
                                self.ack_awaiter.msg_id,
                                extra=MsgLogLevel.L5,
                            )
                        # Reset awaiting ack
                        self.ack_awaiter = None

                # Send message to listeners
                self.proxy.events.fire_event(
                    Event(
                        name=source,
                        event_type=EventType.DATA_RECEIVED,
                        client_id=client_id,
                        event_data=decoded_message,
                        destination=destination,
                        destination_client_id=destination_client_id,
                    )
                )

                # Route message
                await self.message_router.route_message(
                    RoutableMessage(
                        source=source,
                        source_client_id=client_id,
                        destination=destination,
                        destination_client_id=destination_client_id,
                        message=decoded_message,
                    )
                )

                if not self.ack_awaiter:
                    self.release_send_queue()

    async def queue_message(
        self,
        message: RoutableMessage,
        # message: PowerLink31Message | NonPowerLink31Message,
        requires_ack: bool = True,
    ):
        """Add message to send queue for processing."""

        _LOGGER.debug(
            "Queuing Message to %s: %s",
            message.destination,
            message,
        )

        # ACKs should always take highest priority
        # Then in source order
        # if message.message.msg_type in [VIS_ACK, ADM_ACK, NAK]:
        #    priority = 0
        # else:
        priority = self.proxy.clients.get_connection_priority(
            message.source, message.source_client_id
        )

        queue_entry = QueuedMessage(
            q_id=QID.get_next(),
            source=message.source,
            source_client_id=message.source_client_id,
            destination=message.destination,
            destination_client_id=message.destination_client_id,
            message=message.message,
            requires_ack=requires_ack,
        )
        await self.sender_queue.put((priority, queue_entry))
        return True

    async def _send_queue_processor(self):
        """Process send queue."""
        while True:
            # Wait until RTS
            await self.rts.wait()

            queue_message = await self.sender_queue.get()

            message: QueuedMessage = queue_message[1]

            _LOGGER.debug("Retrieved from Send Queue: %s", message)
            # A destination client id of 0 is send to first connection
            # get_connection_info will return the first client connection is passed 0 as client_id
            connection_info = self.proxy.clients.get_client(
                message.destination, message.destination_client_id
            )

            if connection_info:
                # If we did have a desintaiotn client_id of 0
                # Update the destination client_id in the message from our connection info
                # Which should now be our first client
                if message.destination_client_id == 0:
                    message.destination_client_id = connection_info.id

                # Here we wait if the message is destined for a pending connection until
                # it has connected.
                if connection_info.status == ConnectionStatus.CONNECTING:
                    self.pending_has_connected.clear()

                # Wait for the pending connection.  If it is not a pending connection, this will
                # just continuie.
                await self.pending_has_connected.wait()

                msg_id = await self._send_message(message)

                # Send message to listeners
                self.proxy.events.fire_event(
                    Event(
                        message.destination,
                        EventType.DATA_SENT,
                        message.destination_client_id,
                        message.message.data,
                    )
                )

                if (
                    message.message.msg_type in [VIS_BBA, ADM_CID]
                    and message.requires_ack
                    and connection_info.requires_ack
                ):
                    # Hold which connection requires the ACK we receive
                    self.ack_awaiter = WaitingAck(
                        message.destination,
                        message.destination_client_id,
                        message.source,
                        message.source_client_id,
                        msg_id,
                    )
                    _LOGGER.info(
                        "Waiting ACK: From %s %s for %s %s for msg id %s",
                        message.destination,
                        message.destination_client_id,
                        message.source,
                        message.source_client_id,
                        message.message.msg_id,
                        extra=MsgLogLevel.L5,
                    )
                    await self.wait_for_ack(
                        message.destination, message.destination_client_id, msg_id
                    )

            # Message done even if not sent due to no clients
            self.sender_queue.task_done()
            await asyncio.sleep(0.001)

    async def _send_message(self, queued_message: QueuedMessage) -> int | None:
        """Send message.

        return message id for ack tracker
        """
        if self.cb_send_message:
            try:
                # _LOGGER.info("Q: %s", queued_message)
                if isinstance(queued_message.message, NonPowerLink31Message):
                    # Need to build powerlink message before we send
                    if (
                        queued_message.message.msg_id == 0
                        and queued_message.destination != ConnectionName.ALARM_MONITOR
                        and queued_message.message.msg_type == VIS_BBA
                    ):
                        msg_id = self.proxy.message_tracker.get_next_message_id()
                    else:
                        # msgid will be populated if this is an ACK from CM
                        msg_id = queued_message.message.msg_id

                    if queued_message.source == ConnectionName.CM:
                        _LOGGER.debug("Sending : %s", queued_message)

                    queued_message.message = MessageBuilder(
                        self.proxy
                    ).build_powerlink31_message(
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

            await asyncio.sleep(0.1)

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
        # log_message("%s %s-%s waiting for ACK", name, client_id, message_id, level=3)
        self.hold_send_queue()

        # Create timeout event
        timeout = self.proxy.events.fire_event_later(
            self.proxy.config.ACK_TIMEOUT,
            Event(
                name,
                EventType.ACK_TIMEOUT,
                client_id,
                event_data={"msg_id": message_id},
            ),
        )
        await self.rts.wait()
        timeout.cancel()

    async def ack_timeout(self, event: Event):
        """ACK timeout callback."""

        _LOGGER.warning(
            "ACK Timeout: Waiting for ACK from %s for msg id %s",
            event.name,
            event.event_data.get("msg_id", "UNKOWN"),
            extra=MsgLogLevel.L3,
        )
        self.release_send_queue()
