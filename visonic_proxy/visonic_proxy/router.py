"""Message coordinator."""

import asyncio
from collections.abc import Callable
import datetime as dt
from enum import StrEnum
import logging

from .builder import MessageBuilder
from .connections.coordinator import ConnectionCoordinator
from .const import (
    ACTION_COMMAND,
    ADM_ACK,
    ADM_CID,
    DISCONNECT_MESSAGE,
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
)
from .events import Event, EventType, async_fire_event, subscribe
from .helpers import log_message
from .message_tracker import MessageTracker

_LOGGER = logging.getLogger(__name__)


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

        self._unsubscribe_listeners: list[Callable] = []

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

    def set_panel_data(self, event: Event):
        """Set panel data in message builder."""
        # TODO: Better way to do this!
        if event.name == ConnectionName.ALARM and event.event_data.type not in [
            ADM_CID,
            ADM_ACK,
        ]:
            if not MessageBuilder.alarm_serial:
                MessageBuilder.alarm_serial = event.event_data.panel_id
            if not MessageBuilder.account:
                MessageBuilder.account = event.event_data.account_id

    async def data_received(self, event: Event):
        """Handle data received event."""

        # Event data should be a PL31 decoded message
        pl31_message = event.event_data

        # TODO: If receive *ADM-CID this will not ack or do anything to forward
        # Need to fix that
        if event.name == ConnectionName.ALARM:
            # Set panel info
            self.set_panel_data(event)

            # Update tracking info
            try:
                message_no = int(pl31_message.msg_id)
                MessageTracker.last_message_no = message_no
                MessageTracker.last_message_timestamp = dt.datetime.now(dt.UTC)
            except ValueError:
                _LOGGER.warning(
                    "Unrecognised message format from %s %s.  Skipping decoding",
                    event.name,
                    event.client_id,
                )
                _LOGGER.warning("Message: %s", event.event_data(" "))
                _LOGGER.warning("Powerlink: %s", pl31_message)
                return

        func = f"{event.name.lower()}_router"
        if hasattr(self, func):
            await getattr(self, func)(event)

    async def alarm_router(self, event: Event):
        """Route Alarm received message."""
        if self._connection_coordinator.is_disconnected_mode:
            if event.event_data.type == VIS_BBA:
                await self.send_ack_message(event)
        else:
            await self.forward_message(ConnectionName.VISONIC, event)

        # Forward to Alarm Monitor connection
        # Alarm monitor connections do not have same connection id so, send to all
        if event.event_data.type == VIS_BBA:
            if self._connection_coordinator.monitor_server.clients:
                for client_id in self._connection_coordinator.monitor_server.clients:
                    event.client_id = client_id
                    await self.forward_message(ConnectionName.ALARM_MONITOR, event)

    async def visonic_router(self, event: Event):
        """Handle received data."""

        if event.event_data.message.hex(" ") == DISCONNECT_MESSAGE:
            _LOGGER.info("Requesting Visonic to disconnect")
            await self.send_ack_message(event)
            await self._connection_coordinator.stop_client_connection(event.client_id)
        else:
            await self.forward_message(ConnectionName.ALARM, event)

    async def alarm_monitor_router(self, event: Event):
        """Handle received data."""

        # TODO: Here we need to add a filter to drop messages but still ACK them
        # and also to respond to E0 requests
        # Respond to command requests
        if event.event_data.message[1:2].hex().lower() == ACTION_COMMAND.lower():
            await self.do_action_command(event)
        elif event.event_data.type == VIS_BBA:
            await self.forward_message(ConnectionName.ALARM, event)
            await self.send_ack_message(event)

    async def do_action_command(self, event: Event):
        """Perform command from ACTION COMMAND message."""
        command = event.event_data.message[2:3].hex()

        if command == "01":  # Send status
            await self._connection_coordinator.send_status_message(event.name)
        elif command == "02":  # Request Visonic disconnection
            if self._connection_coordinator.visonic_clients:
                client_id = list(self._connection_coordinator.visonic_clients.keys())[0]
                await async_fire_event(
                    Event(
                        ConnectionName.VISONIC, EventType.REQUEST_DISCONNECT, client_id
                    )
                )

    async def forward_message(
        self,
        destination: ConnectionName,
        event: Event,
    ):
        """Forward message to destination."""
        if destination == ConnectionName.VISONIC:
            if not self._connection_coordinator.visonic_clients:
                return

        if destination == ConnectionName.ALARM_MONITOR:
            message = event.event_data.message
        else:
            message = event.event_data.original_message

        # TODO: Add here to send or not send based on is connected and a
        # param that just blocks sending.

        await self._connection_coordinator.queue_message(
            source=event.name,
            destination=destination,
            client_id=event.client_id,
            message_id=event.event_data.msg_id,
            readable_message=event.event_data.message.hex(" "),
            message=message,
            is_ack=event.event_data.type == VIS_ACK,
            requires_ack=event.event_data.type == VIS_BBA,
        )
        log_message(
            "FORWARDER: %s -> %s %s %s",
            event.name,
            destination,
            event.client_id,
            int(event.event_data.msg_id),
            level=6,
        )

    async def send_ack_message(self, event: Event):
        """Send ACK message."""
        ack_message = self._message_builer.build_ack_message(event.event_data.msg_id)
        await self._connection_coordinator.queue_message(
            ConnectionName.CM,
            event.name,
            event.client_id,
            event.event_data.msg_id,
            ack_message.message,
            ack_message.msg_data,
            is_ack=True,
            requires_ack=False,
        )

    async def send_keepalive(self, event: Event):
        """Handle sending keepalive."""
        # TODO: Put in coordinator
        message_no = MessageTracker.get_next()
        ka_message = self._message_builer.build_keep_alive_message(message_no)
        await self._connection_coordinator.queue_message(
            ConnectionName.CM,
            event.name,
            event.client_id,
            message_no,
            "KEEPALIVE",
            ka_message.msg_data,
        )
