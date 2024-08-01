"""Message coordinator."""

import asyncio
from collections.abc import Callable
import datetime as dt
from enum import StrEnum
import logging

from .builder import MessageBuilder
from .connections.coordinator import ConnectionCoordinator
from .const import (
    ACK_B0_03_MESSAGES,
    ACTION_COMMAND,
    ADM_ACK,
    ADM_CID,
    ALARM_MONITOR_SENDS_ACKS,
    DUH,
    NAK,
    PROXY_MODE,
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
    ManagedMessages,
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
        if event.name == ConnectionName.ALARM and event.event_data.msg_type not in [
            ADM_CID,
            ADM_ACK,
        ]:
            if not MessageBuilder.alarm_serial:
                MessageBuilder.alarm_serial = event.event_data.panel_id
            if not MessageBuilder.account:
                MessageBuilder.account = event.event_data.account_id

    async def data_received(self, event: Event):
        """Handle data received event."""

        # Event data should be a PowerLink31Message or NonPowerLink31Message (from Alarm Monitor)
        message = event.event_data

        if event.name == ConnectionName.ALARM:
            # Set panel info
            self.set_panel_data(event)

            # Update tracking info
            try:
                message_no = int(message.msg_id)
                MessageTracker.last_message_no = message_no
                MessageTracker.last_message_timestamp = dt.datetime.now(dt.UTC)
            except ValueError:
                _LOGGER.warning(
                    "Unrecognised message format from %s %s.  Skipping decoding",
                    event.name,
                    event.client_id,
                )
                _LOGGER.warning("Message: %s", event.event_data(" "))
                _LOGGER.warning("Powerlink: %s", message)
                return

        # Route ACKs - all ACK messages should have a destination populated.  If not, dump it.
        log_message("REC MSG: %s", event, level=6)
        if event.event_data.msg_type in [
            VIS_ACK,
            ADM_ACK,
            NAK,
            DUH,
        ]:  # TODO: Check this list should have NAK and DUH
            # TODO: Add here if should create ACK, not send etc

            if (
                event.event_data.msg_type in [ADM_ACK, NAK]
                and event.name == ConnectionName.VISONIC
            ):
                # Just forward this to the Alarm.
                # TODO: Why does it not receive destination info from flow manager?
                await self.forward_message(ConnectionName.ALARM, event.client_id, event)

            elif event.destination and event.destination_client_id:
                # If it is an ACK, we expect to have destination and desitnation_client_id
                # If we don't, just dump it
                await self.forward_message(
                    event.destination, event.destination_client_id, event
                )
            elif not PROXY_MODE and event.name == ConnectionName.ALARM_MONITOR:
                await self.forward_message(
                    ConnectionName.ALARM,
                    self._connection_coordinator.alarm_server.get_first_client_id(),
                    event,
                    False,
                )

        else:
            # Route VIS-BBA messages
            func = f"{event.name.lower()}_router"
            if hasattr(self, func):
                await getattr(self, func)(event)

    async def alarm_router(self, event: Event):
        """Route Alarm received VIS-BBA and *ADM-CID messages."""
        if self._connection_coordinator.is_disconnected_mode:
            # If in disconnected mode and Alarm Monitor does not send ACKs, send one to Alarm.
            if event.event_data.msg_type == VIS_BBA and not ALARM_MONITOR_SENDS_ACKS:
                await self.send_ack_message(event)

        elif not self._connection_coordinator.is_disconnected_mode:
            # If not in disconnected mode, forward everything to Visonic
            await self.forward_message(ConnectionName.VISONIC, event.client_id, event)

        # Forward to all Alarm Monitor connections
        # Alarm monitor connections do not have same connection id so, send to all
        if self._connection_coordinator.monitor_server.clients:
            if (
                self._connection_coordinator.is_disconnected_mode
                and ACK_B0_03_MESSAGES
                and event.event_data.message_class == "b0"
            ):
                log_message("CREATING ACK: %s", event, level=6)
                await self.send_ack_message(event)
            for client_id in self._connection_coordinator.monitor_server.clients:
                await self.forward_message(
                    ConnectionName.ALARM_MONITOR,
                    client_id,
                    event,
                    requires_ack=event.event_data.message_class != "b0",
                )

    async def visonic_router(self, event: Event):
        """Route Visonic received VIS-BBA and *ADM-CID messages."""

        if event.event_data.data.hex(" ") == ManagedMessages.DISCONNECT_MESSAGE:
            # Manage the disconnect message comming from Visonic to the Alarm
            # Do not forward to Alarm, but send ACK back to Visonic and then request
            # a disconnect for the Visonic connection.
            await self.send_ack_message(event)
            await asyncio.sleep(1)
            _LOGGER.info("Requesting Visonic to disconnect")
            await self._connection_coordinator.stop_client_connection(event.client_id)

            # As we do not forward this disconnect message to the Alarm in order to keep it
            # connected, we need to send something to the Alarm to keep the message IDs in sync.
            # So, send a KEEPALIVE message to do thid.
            event.name = ConnectionName.ALARM
            await self.send_keepalive(event)
        else:
            # Forward all non managed messages to the Alarm connection
            await self.forward_message(ConnectionName.ALARM, event.client_id, event)

    async def ha_router(self, event: Event):
        """Route Alarm Monitor received VIS-BBA messages.

        Will receive NonPowerLink31Message in event_data
        """
        # TODO: Here we need to add a filter to drop messages but still ACK them
        # and also to respond to E0 requests
        alarm_client_id = (
            self._connection_coordinator.alarm_server.get_first_client_id()
        )

        # Respond to command requests
        if event.event_data.data[1:2].hex().lower() == ACTION_COMMAND.lower():
            await self.do_action_command(event)

        elif event.event_data.data == bytes.fromhex(ManagedMessages.STOP):
            await self.forward_message(
                ConnectionName.ALARM, alarm_client_id, event, requires_ack=False
            )

        else:
            await self.forward_message(
                ConnectionName.ALARM, alarm_client_id, event, requires_ack=True
            )

            if event.event_data.data == bytes.fromhex(ManagedMessages.DOWNLOAD_MODE):
                # Alarm Monitor has requested to download EPROM.  Need to disconnect Visonic
                # and only reconnect when Monitor sends DOWNLOAD_EXIT or timesout after 5 mins
                await self._connection_coordinator.set_download_mode(True)
            elif event.event_data.data == bytes.fromhex(
                ManagedMessages.EXIT_DOWNLOAD_MODE
            ):
                await self._connection_coordinator.set_download_mode(False)

    async def do_action_command(self, event: Event):
        """Perform command from ACTION COMMAND message."""
        command = event.event_data.data[2:3].hex()

        if command == "01":  # Send status
            if self._connection_coordinator.monitor_server.clients:
                for client_id in self._connection_coordinator.monitor_server.clients:
                    await self._connection_coordinator.send_status_message(
                        event.name, client_id
                    )
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
        destination_client_id: str,
        event: Event,
        requires_ack: bool = True,
    ):
        """Forward message to destination."""
        if destination == ConnectionName.VISONIC:
            if not self._connection_coordinator.visonic_clients:
                return

        # TODO: Add here to send or not send based on is connected and a
        # param that just blocks sending.

        await self._connection_coordinator.queue_message(
            source=event.name,
            source_client_id=event.client_id,
            destination=destination,
            destination_client_id=destination_client_id,
            message=event.event_data,
            requires_ack=requires_ack,
        )

        log_message(
            "FORWARDER: %s -> %s %s %s - %s",
            event.name,
            destination,
            event.client_id,
            event.event_data.msg_id,
            event.event_data.data,
            level=6,
        )

    async def send_ack_message(self, event: Event):
        """Send ACK message."""
        ack_message = self._message_builer.build_ack_message(event.event_data.msg_id)
        await self._connection_coordinator.queue_message(
            ConnectionName.CM, 0, event.name, event.client_id, ack_message
        )

    async def send_keepalive(self, event: Event):
        """Handle sending keepalive."""
        # TODO: Put in coordinator
        ka_message = self._message_builer.build_keep_alive_message()
        await self._connection_coordinator.queue_message(
            ConnectionName.CM,
            0,
            event.name,
            event.client_id,
            ka_message,
        )
