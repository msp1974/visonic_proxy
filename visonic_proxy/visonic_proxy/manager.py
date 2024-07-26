"""Message coordinator."""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
import logging
from operator import attrgetter
import datetime as dt

from .builder import MessageBuilder, MessageItem
from .connections.manager import ConnectionManager, ConnectionProfile, Forwarder
from .const import (
    ADM_ACK,
    ADM_CID,
    MESSAGE_LOG_LEVEL,
    VIS_ACK,
    VIS_BBA,
    Commands,
    ConnectionName,
    MessagePriority,
)
from .decoders.pl31_decoder import PowerLink31MessageDecoder


_LOGGER = logging.getLogger(__name__)


class MessageCoordinatorStatus(StrEnum):
    """Message coordinator status Enum."""

    STOPPED = "stopped"
    RUNNING = "running"
    CLOSING = "closing"


@dataclass
class MessageTracker:
    """Tracker for messages."""

    last_message_no: int = 0
    last_message_timestamp: dt.datetime = 0

    def get_next(self):
        """Get next msg id."""
        return self.last_message_no + 1
    
    def get_current(self):
        """Get current/last message id"""
        return self.last_message_no

@dataclass
class AckTracker:
    """Track connections waiting for ack."""
    _waiting_ack: list = field(default_factory=list)

    def add_awaiting_ack(self, source: ConnectionName, client_id: str):
        ack_id = f"{source}_{client_id}"
        if ack_id not in self._waiting_ack:
            self._waiting_ack.append(f"{source}_{client_id}")

    def remove_awaiting_ack(self, source: ConnectionName, client_id: str):
        ack_id = f"{source}_{client_id}"
        if ack_id in self._waiting_ack:
            self._waiting_ack.remove(ack_id)

    def is_awaiting_ack(self, source: ConnectionName, client_id: str):
        ack_id = f"{source}_{client_id}"
        if ack_id in self._waiting_ack:
            return True
        return False
    
class QueueID:
    """Queue message id generator."""

    _id: int = 0

    @staticmethod
    def get():
        """Get queue id."""
        QueueID._id += 1
        return QueueID._id


@dataclass
class QueuedMessage:
    """Queued message"""

    queue_id: int
    priority: MessagePriority = MessagePriority.LOW
    destination: ConnectionName | None = None
    client_id: str | None = None
    message: bytes = None


class MessageQueue:
    """Message queue."""

    def __init__(self):
        self._queue: list[QueuedMessage] = []
        self._queue_id = QueueID()
        self._last_id: int = 0

    @property
    def queue_length(self) -> int:
        """Get queue length."""
        return len(self._queue)

    def put(
        self,
        destination: ConnectionName,
        client_id: str,
        message: bytes,
        priority: MessagePriority = MessagePriority.LOW,
    ):
        """Put message on queue."""
        q_id = self._queue_id.get()
        self._queue.append(
            QueuedMessage(
                queue_id=q_id,
                priority=priority,
                destination=destination,
                client_id=client_id,
                message=message,
            )
        )

    def get(self) -> QueuedMessage:
        """Get message from queue."""
        if len(self._queue) > 0:
            prioritised_list = sorted(
                self._queue, key=attrgetter("priority", "queue_id")
            )
            msg = prioritised_list[0]
            self._last_id = msg.queue_id
            return msg.destination, msg.client_id, msg.message

    def processed(self):
        """Remove queued message from queue as now processed."""
        for idx, msg in enumerate(self._queue):
            if msg.queue_id == self._last_id:
                self._queue.pop(idx)
                return

    def clear(self):
        """Clear message queue."""
        self._queue = []


class MessageCoordinator:
    """Class for message coordinator

    Ensures flow control of Request -> ACK -> Response
    Ensures messages from one connection get routed to the right other connection
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        connection_profiles: list[ConnectionProfile],
    ):
        """Init."""
        self._loop = loop
        self.connection_profiles = connection_profiles

        self.status: MessageCoordinatorStatus = MessageCoordinatorStatus.STOPPED

        self._connection_manager = ConnectionManager(
            loop, self.received_message, self.send_keepalive
        )
        self._sender_task: asyncio.Task = None

        self._tracker = MessageTracker()
        self._ack_tracker = AckTracker()
        self._message_builer = MessageBuilder()
        self.pl31_message_decoder = PowerLink31MessageDecoder()
        self._message_queue = MessageQueue()


    def log_message(self, message: str, *args, level: int = 5):
        """Log message to logger if level."""
        if MESSAGE_LOG_LEVEL >= level:
            _LOGGER.info(message, *args)

    def get_profile(self, name: ConnectionName) -> ConnectionProfile | None:
        """Get conneciton profile."""
        for profile in self.connection_profiles:
            if profile.name == name:
                return profile

    async def start(self):
        """Start message coordinator."""

        for connection in self.connection_profiles:
            self._connection_manager.add_connection(connection)

        # Start connection manager
        await self._connection_manager.start()

        # Start message sender task
        self._sender_task = self._loop.create_task(
            self._message_sender_task(), name="Message Sender Task"
        )

        self.status = MessageCoordinatorStatus.RUNNING
        _LOGGER.info("Message Coordinator Started")

    async def stop(self):
        """Stop message coordinator."""
        _LOGGER.debug("Stopping Message Coordinator")
        self.status = MessageCoordinatorStatus.CLOSING

        # Stop message sender
        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
            _LOGGER.debug("Message sender cancelled")

        await self._connection_manager.stop()
        self.status = MessageCoordinatorStatus.STOPPED
        _LOGGER.info("Message Coordinator Stopped")

    def message_preprocessor(self, msg: bytes) -> MessageItem:
        """Preprocessor for using injector to send message to alarm

        Messages can be injected in:
         Full format - 0d b0 01 6a 00 43 a0 0a \ 0d a2 00 00 08 00 00 00 00 00 00 00 43 12 0a
         Partial format - b0 01 6a 43 \ a2 00 00 08 00 00 00 00 00 00 00 43
         Short format (for B0 messages only) - b0 6a / b0 17 18 24
        """
        if msg[:1] == b"\x0d" and msg[-1:] == b"\x0a":
            
            if msg[1:2] == b"\x02":
                # Received ack message.  Use build_ack_message to ensure correct ACK type
                message = self._message_builer.build_ack_message(self._tracker.get_current())
            else:
                message = self._message_builer.build_powerlink31_message(
                    self._tracker.get_next(), msg.hex(" ")
                )
            return message.msg_data
        
        # Else deal with shortcut commands
        if msg[:1] == b"\xb0":
            if msg[-1:] != b"\x43":
                command = msg[1:2].hex()
                params = msg[2:].hex(" ")
                message = self._message_builer.build_b0_request(
                    self._tracker.get_next(), command, params
                )
            else:
                message = self._message_builer.build_b0_partial_request(
                    self._tracker.get_next(), msg.hex(" ")
                )
        else:
            message = self._message_builer.build_std_request(
                self._tracker.get_next(), msg
            )
        return message.msg_data

    def execute_command(self, command: Commands):
        """Execute command."""
        if command == "SHUTDOWN":
            _LOGGER.debug("Shutdown requested")
            self._loop.create_task(self.stop())

    def received_message(
        self,
        source: ConnectionName,
        client_id: str,
        command: bool,
        destinations: list[Forwarder] | str,
        data: bytes | str,
    ):
        """Handle received message"""

        if command:
            _LOGGER.info("Received command action: %s", data)
            # Handle control messages
            self.execute_command(data)
        else:
            # If we send short commands (from injector), build into
            # full message to send to Alarm
            if self.get_profile(source).preprocess:
                data = self.message_preprocessor(data)

            # log_message("Message received from %s %s", source, client_id, level=3)

            # Decode powerlink 31 wrapper
            pl31_message = self.pl31_message_decoder.decode_powerlink31_message(data)

            # Track acks if set to do so
            profile = self._connection_manager.get_profile(source)
            if profile.track_acks and pl31_message.type == VIS_BBA:
                self._ack_tracker.add_awaiting_ack(source, client_id)

            self.log_message(
                    "\x1b[1;36m%s %s %s RAW ->\x1b[0m %s", source, pl31_message.panel_id, client_id, data.hex(" "), level=6
                )
            if pl31_message.type == VIS_ACK:
                self.log_message(
                    "\x1b[1;35m%s %s %s ACK ->\x1b[0m %s", source, pl31_message.panel_id, client_id, pl31_message.message.hex(" "), level=4
                )
            else:
                self.log_message(
                    "\x1b[1;32m%s %s %s ->\x1b[0m %s", source, pl31_message.panel_id, client_id, pl31_message.message.hex(" "), level=1
                )

            # If message should be forwarded
            if destinations:
                for forwarder in destinations:
                    dest_client_ids = []
                    dest_profile = self._connection_manager.get_profile(forwarder.destination)

                    if forwarder.forward_to_all_connections:
                        connection = self._connection_manager.get_connection(
                            forwarder.destination
                        )
                        if hasattr(connection.connection, "clients") and connection.connection.clients:
                            dest_client_ids = [client_id for client_id in connection.connection.clients.keys()]
                    else:
                        dest_client_ids = [client_id]

                    _LOGGER.debug("FORWARD DESTS: %s %s", forwarder.destination, dest_client_ids)

                    for dest_client_id in dest_client_ids:
                        if pl31_message.type == VIS_ACK and profile.ignore_incomming_acks:
                            self.log_message("\x1b[1;33mNot forwarding ACK from %s %s %s\x1b[0m - set to ignore incomming ACKs", source, pl31_message.panel_id, client_id, level=4)
                            continue

                        if pl31_message.type == VIS_ACK and dest_profile.track_acks and not self._ack_tracker.is_awaiting_ack(dest_profile.name, dest_client_id):
                            self.log_message("\x1b[1;33mNot forwarding ACK to %s %s %s\x1b[0m - request was not from this connetion", dest_profile.name, pl31_message.panel_id, dest_client_id, level=4)
                            continue

                        self._ack_tracker.remove_awaiting_ack(dest_profile.name, dest_client_id)

                        if pl31_message.type == VIS_ACK:
                            self.log_message(
                                "\x1b[1;35mForwarding ACK ->\x1b[0m %s %s",
                                forwarder.destination,
                                dest_client_id,
                                level=4,
                            )
                        else:
                            self.log_message(
                                "\x1b[1;32mForwarding ->\x1b[0m %s %s",
                                forwarder.destination,
                                dest_client_id,
                                level=2,
                            )
                        if forwarder.remove_pl31_wrapper:
                            self._message_queue.put(
                                forwarder.destination,
                                dest_client_id,
                                pl31_message.message,
                                MessagePriority.IMMEDIATE,
                            )
                        else:
                            self._message_queue.put(
                                forwarder.destination,
                                dest_client_id,
                                data,
                                MessagePriority.IMMEDIATE,
                            )

            # Update message tracker with last message number from PowerLink31 message
            # and timestamp of this last message (used for keepalive)
            try:
                message_no = int(pl31_message.msg_id)
            except ValueError:
                _LOGGER.warning("Unrecognised message format.  Skipping decoding")
                self.log_message("Message: %s", data.hex(" "), level=0)
                self.log_message("Powerlink: %s", pl31_message, level=0)
                return

            self._tracker.last_message_no = message_no
            self._tracker.last_message_timestamp = dt.datetime.now(dt.UTC)

            # Update serial and account no if not set, but only on a message from alarm
            # which should be first message received
            # ADM-CID sends in wrong order so ignore
            if source == ConnectionName.ALARM and pl31_message.type not in [
                ADM_CID,
                ADM_ACK,
            ]:
                if not self._message_builer.alarm_serial:
                    self._message_builer.alarm_serial = pl31_message.panel_id
                if not self._message_builer.account:
                    self._message_builer.account = pl31_message.account_id

            # If message is not an ACK and we need to send the ACKs
            if pl31_message.type != VIS_ACK:
                if self.requires_ack(source):
                    self.send_ack(source, client_id, pl31_message.msg_id)

    def send_keepalive(self, destination: ConnectionName, client_id: str = ""):
        """Send keepalive message"""
        
        msg = self._message_builer.build_keep_alive_message(
            self._tracker.last_message_no + 1
        )
        self.log_message(
            "\x1b[1;32mCM KEEPALIVE ->\x1b[0m %s %s -> %s",
            destination,
            client_id,
            "0d b0 01 6a 00 43 a0 0a",
            level=3,
        )
        self._message_queue.put(
            destination, client_id, msg.msg_data, MessagePriority.HIGH
        )

    def requires_ack(self, connection_name: ConnectionName) -> bool:
        """If connection requires ack."""
        for profile in self.connection_profiles:
            if profile.name == connection_name and profile.ack_received_messages:
                return True
        return False

    def send_ack(self, destination: ConnectionName, client_id: str, msg_id: int):
        """Send ACK message."""
        msg = self._message_builer.build_ack_message(msg_id)
        _LOGGER.debug("Sending ACK to %s: %s", destination, msg)
        self._message_queue.put(
            destination, client_id, msg.msg_data, MessagePriority.IMMEDIATE
        )

    async def _message_sender_task(self):
        """Message sender task

        Runs in an async task
        """
        retry = 0
        _LOGGER.debug("Message Send Queue Manager started")
        while True:
            # Get next highest priority message
            if self._message_queue.queue_length == 0:
                await asyncio.sleep(0.005)
                continue
            _LOGGER.debug("Queued messages: %s", self._message_queue.queue_length)
            destination, client_id, message = self._message_queue.get()
            if message:
                # See if the destination is connected and send
                connection = self._connection_manager.get_connection(
                    destination, client_id
                )

                _LOGGER.debug("WRITE CONNECTION: %s", connection)
                if connection:
                    _LOGGER.debug(
                        "Sending message to %s %s -> %s",
                        destination,
                        client_id,
                        message,
                    )
                    try:
                        self._connection_manager.send_message(
                            destination, client_id, message
                        )
                        self._message_queue.processed()
                        retry = 0
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        retry += 1
                        _LOGGER.error(
                            "Error sending message to %s %s. %s",
                            destination,
                            client_id,
                            ex,
                        )
                else:
                    # Give it time to reconnect
                    retry += 1
                    _LOGGER.warning(
                        "No connection to %s %s available to send message. Attempt %s",
                        destination,
                        client_id,
                        retry,
                    )
                    await asyncio.sleep(2)

            # Dump message if exceeded retry
            if retry >= 15:
                self._message_queue.processed()
                retry = 0
