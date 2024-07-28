"""Message coordinator."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
from enum import StrEnum
import logging

from .builder import MessageBuilder
from .connections.coordinator import ConnectionCoordinator
from .const import ADM_ACK, ADM_CID, MESSAGE_LOG_LEVEL, VIS_ACK, ConnectionName
from .decoders.pl31_decoder import PowerLink31Message, PowerLink31MessageDecoder
from .events import Event, EventType, subscribe

_LOGGER = logging.getLogger(__name__)


@dataclass
class MessageTracker:
    """Tracker for messages."""

    last_message_no: int = 0
    last_message_timestamp: dt.datetime = 0

    def get_next(self):
        """Get next msg id."""
        return self.last_message_no + 1

    def get_current(self):
        """Get current/last message id."""
        return self.last_message_no


class MessageCoordinatorStatus(StrEnum):
    """Message coordinator status Enum."""

    STOPPED = "stopped"
    RUNNING = "running"
    CLOSING = "closing"


class MessageRouter:
    """Class for message router.

    Ensures flow control of Request -> ACK -> Response
    Ensures messages from one connection get routed to the right other connection
    """

    def __init__(
        self,
    ):
        """Init."""
        self._loop = asyncio.get_running_loop()

        self.status: MessageCoordinatorStatus = MessageCoordinatorStatus.STOPPED

        self._connection_coordinator = ConnectionCoordinator()
        self._message_builer = MessageBuilder()
        self._tracker = MessageTracker()
        self.pl31_message_decoder = PowerLink31MessageDecoder()

        self._unsubscribe_listeners: list[Callable] = []

    def log_message(self, message: str, *args, level: int = 5):
        """Log message to logger if level."""
        if level <= MESSAGE_LOG_LEVEL:
            _LOGGER.info(message, *args)

    async def start(self):
        """Start message coordinator."""

        # Start connection manager
        await self._connection_coordinator.start()

        # Subscribe to events
        self._unsubscribe_listeners = [
            subscribe("ALL", EventType.DATA_RECEIVED, self.data_received),
            subscribe("ALL", EventType.SEND_KEEPALIVE, self.send_keepalive),
        ]

        self.status = MessageCoordinatorStatus.RUNNING
        _LOGGER.info("Message Coordinator Started")

    async def stop(self):
        """Stop message coordinator."""
        _LOGGER.debug("Stopping Message Coordinator")
        self.status = MessageCoordinatorStatus.CLOSING

        await self._connection_coordinator.stop()
        self.status = MessageCoordinatorStatus.STOPPED
        _LOGGER.info("Message Coordinator Stopped")

    def set_panel_data(self, source, pl31_message: PowerLink31Message):
        """Set panel data in message builder."""
        # TODO: Better way to do this!
        if source == ConnectionName.ALARM and pl31_message.type not in [
            ADM_CID,
            ADM_ACK,
        ]:
            if not MessageBuilder.alarm_serial:
                MessageBuilder.alarm_serial = pl31_message.panel_id
            if not MessageBuilder.account:
                MessageBuilder.account = pl31_message.account_id

    async def data_received(self, event: Event):
        """Handle data received event."""
        func = f"{event.name.lower()}_data_received"
        if hasattr(self, func):
            await getattr(self, func)(event)

    async def alarm_data_received(self, event: Event):
        """Handle received data."""

        # Decode powerlink 31 wrapper
        pl31_message = self.pl31_message_decoder.decode_powerlink31_message(
            event.event_data
        )

        # Set panel info
        self.set_panel_data(event.name, pl31_message)

        # TODO: If receive *ADM-CID this will not ack or do anything to forward
        # Need to fix that
        try:
            message_no = int(pl31_message.msg_id)
            self._tracker.last_message_no = message_no
            self._tracker.last_message_timestamp = dt.datetime.now(dt.UTC)
        except ValueError:
            _LOGGER.warning("Unrecognised message format.  Skipping decoding")
            _LOGGER.warning("Message: %s", event.event_data(" "))
            _LOGGER.warning("Powerlink: %s", pl31_message)
            return

        if pl31_message.type == VIS_ACK:
            _LOGGER.info("%s->CM  ACK %s", event.name, pl31_message.message.hex(" "))
        else:
            _LOGGER.info("%s->CM  MSG %s", event.name, pl31_message.message.hex(" "))

        # TODO: Tesing - send ACK
        if pl31_message.type != VIS_ACK:
            ack_message = self._message_builer.build_ack_message(message_no)
            _LOGGER.info("CM->%s  ACK %s", event.name, ack_message.message)
            await self._connection_coordinator.send_message(
                ConnectionName.CM,
                ConnectionName.ALARM,
                event.client_id,
                pl31_message.msg_id,
                ack_message.msg_data,
            )

        # Forward data
        # Visonic
        if self._connection_coordinator.visonic_clients:
            if pl31_message.type == VIS_ACK:
                _LOGGER.info("CM->VISONIC  ACK %s", pl31_message.message.hex(" "))
            else:
                _LOGGER.info("CM->VISONIC  MSG %s", pl31_message.message.hex(" "))
            await self._connection_coordinator.send_message(
                event.name,
                ConnectionName.VISONIC,
                event.client_id,
                pl31_message.msg_id,
                event.event_data,
            )

    async def visonic_data_received(self, event: Event):
        """Handle received data."""
        pl31_message = self.pl31_message_decoder.decode_powerlink31_message(
            event.event_data
        )
        _LOGGER.info("VISONIC->CM  MSG %s", pl31_message.message.hex(" "))

        # Send to alarm
        # TODO: Make this a filter function
        if (
            pl31_message.message.hex(" ")
            == "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"
        ):
            _LOGGER.info("Requesting Visonic to disconnect")
            await self._connection_coordinator.stop_client_connection(event.client_id)
        elif pl31_message.type == VIS_ACK:
            pass
        else:
            await self._connection_coordinator.send_message(
                event.name,
                ConnectionName.ALARM,
                event.client_id,
                pl31_message.msg_id,
                event.event_data,
            )
            _LOGGER.info(
                "CM->%s  MSG %s", ConnectionName.ALARM, pl31_message.message.hex(" ")
            )

    async def alarm_monitor_data_received(self, event: Event):
        """Handle received data."""

        message = self._message_builer.message_preprocessor(
            self._tracker.get_next(), event.event_data
        )
        _LOGGER.info("%s->CM  MSG %s", event.name, message.message)
        await self._connection_coordinator.send_message(
            event.name,
            ConnectionName.ALARM,
            event.client_id,
            message.msg_id,
            message.msg_data,
        )
        _LOGGER.info("CM->%s  MSG %s", ConnectionName.ALARM, message.message)

    async def send_keepalive(self, event: Event):
        """Handle sending keepalive."""
        # TODO: Put in coordinator
        message_no = self._tracker.get_next()
        ka_message = self._message_builer.build_keep_alive_message(message_no)
        _LOGGER.info("CM->%s  K-A %s", event.name, ka_message.message)
        await self._connection_coordinator.send_message(
            ConnectionName.CM,
            event.name,
            event.client_id,
            message_no,
            ka_message.msg_data,
        )
