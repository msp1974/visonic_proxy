"""Message coordinator."""

import asyncio
from collections.abc import Callable
from enum import StrEnum
import logging

from .builder import MessageBuilder
from .connections.coordinator import ConnectionCoordinator
from .const import (
    ACK_B0_03_MESSAGES,
    ACTION_COMMAND,
    ADM_ACK,
    ADM_CID,
    ALARM_MONITOR_NEEDS_ACKS,
    ALARM_MONITOR_SENDS_ACKS,
    DUH,
    NAK,
    VIS_ACK,
    VIS_BBA,
    ConnectionName,
    ManagedMessages,
)
from .events import Event, EventType, async_fire_event, subscribe
from .filter import is_filtered
from .helpers import log_message

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

    async def data_received(self, event: Event):
        """Handle data received event."""

        # Event data should be a PowerLink31Message or NonPowerLink31Message (from Alarm Monitor)

        log_message("REC MSG: %s", event, level=6)

        # ---------------------------------------------------------------
        # ACK Messages
        # ---------------------------------------------------------------

        # Route ACKs - all ACK messages should have a destination populated.  If not, dump it.
        if event.event_data.msg_type in [VIS_ACK, ADM_ACK, NAK, DUH]:
            # TODO: Check this list should have NAK and DUH
            # TODO: Add here if should create ACK, not send etc

            # ---------------------------------------------------------------
            # ALARM
            # ---------------------------------------------------------------
            if event.name == ConnectionName.ALARM:
                pass

            # ---------------------------------------------------------------
            # VISONIC
            # ---------------------------------------------------------------
            if event.name == ConnectionName.VISONIC:
                await self.forward_message(ConnectionName.ALARM, event.client_id, event)
                return

            # ---------------------------------------------------------------
            # ALARM MONITOR
            # ---------------------------------------------------------------
            if event.name == ConnectionName.ALARM_MONITOR:
                if self._connection_coordinator.is_disconnected_mode:
                    # Must be for Alarm
                    await self.forward_message(
                        ConnectionName.ALARM,
                        self._connection_coordinator.alarm_server.get_first_client_id(),
                        event,
                        False,
                    )
                return

            # ---------------------------------------------------------------
            # ALL
            # ---------------------------------------------------------------

            if event.destination and event.destination_client_id:
                # If it is an ACK, we expect to have destination and desitnation_client_id
                # If we don't, just dump it
                await self.forward_message(
                    event.destination, event.destination_client_id, event
                )
                return

            if event.destination != ConnectionName.CM:
                _LOGGER.warning("ACK received with no destination. %s", event)

            return

        # Route VIS-BBA messages
        func = f"{event.name.lower()}_router"
        if hasattr(self, func):
            await getattr(self, func)(event)

    async def alarm_router(self, event: Event):
        """Route Alarm received VIS-BBA and *ADM-CID messages."""
        if self._connection_coordinator.is_disconnected_mode:
            # if disconnected from Visonic
            if event.event_data.msg_type == VIS_BBA and (
                # No Monitor or Visonic connected
                not self._connection_coordinator.monitor_server.clients
                # Monitor connected but it doesn't send ACKs
                or not ALARM_MONITOR_SENDS_ACKS
            ):
                # Send ACK from CM to Alarm
                await self.send_ack_message(event)

            # For loggin what Alarm sent
            if not self._connection_coordinator.monitor_server.clients:
                log_message(
                    "%s->%s %s-%s %s %s",
                    event.name,
                    ConnectionName.CM,
                    event.client_id,
                    f"{event.event_data.msg_id:0>4}",
                    event.event_data.msg_type,
                    event.event_data.data.hex(" "),
                    level=2 if event.event_data.msg_type == VIS_ACK else 1,
                )

        else:
            # If not in disconnected mode, forward everything to Visonic
            await self.forward_message(ConnectionName.VISONIC, event.client_id, event)

        # Forward to all Alarm Monitor connections
        # Alarm monitor connections do not have same connection id so, send to all
        if self._connection_coordinator.monitor_server.clients:
            # Do not forward *ADM-CID messages
            if event.event_data.msg_type == ADM_CID:
                return

            if (
                self._connection_coordinator.is_disconnected_mode
                and ACK_B0_03_MESSAGES
                and event.event_data.message_class == "b0"
            ):
                await self.send_ack_message(event)

            # Set things going to Alarm Monitor that do not need ACKs
            requires_ack = True
            if (
                event.event_data.message_class == "b0"
                or event.event_data.data
                == bytes.fromhex(ManagedMessages.OUT_OF_DOWNLOAD_MODE)
            ):
                requires_ack = False

            for client_id in self._connection_coordinator.monitor_server.clients:
                await self.forward_message(
                    ConnectionName.ALARM_MONITOR,
                    client_id,
                    event,
                    requires_ack=requires_ack,
                )

    async def visonic_router(self, event: Event):
        """Route Visonic received VIS-BBA and *ADM-CID messages."""

        if event.event_data.data.hex(" ") == ManagedMessages.DISCONNECT_MESSAGE:
            # Manage the disconnect message comming from Visonic to the Alarm
            # Do not forward to Alarm, but send ACK back to Visonic and then request
            # a disconnect for the Visonic connection.
            log_message(
                "%s %s requested to disconnect", event.name, event.client_id, level=1
            )
            await self.send_ack_message(event)
            await asyncio.sleep(1)

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
            return

        # Set DOWNLOAD mode
        # TODO: Dont fix this message class here!!
        if (
            event.event_data.data == bytes.fromhex(ManagedMessages.BUMP)
            or event.event_data.message_class == "24"
        ):
            # Alarm Monitor has requested to download EPROM.  Need to disconnect Visonic
            # and only reconnect when Monitor sends DOWNLOAD_EXIT or timesout after 5 mins
            await self._connection_coordinator.set_stealth_mode(True)

        # Unset DOWNLOAD mode
        if event.event_data.data == bytes.fromhex(ManagedMessages.EXIT_DOWNLOAD_MODE):
            await self._connection_coordinator.set_stealth_mode(False)

        # Filter messages from being sent to Alarm
        if is_filtered(event.event_data.data):
            log_message("Not sending message due to filter", level=2)
            if ALARM_MONITOR_NEEDS_ACKS:
                await self.send_ack_message(event)
            return

        # Forward message to Alarm
        await self.forward_message(
            ConnectionName.ALARM, alarm_client_id, event, requires_ack=True
        )

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
        ack_message = self._message_builer.build_ack_message(
            event.event_data.msg_id, not self._connection_coordinator.stealth_mode
        )
        log_message(
            "Generating ACK: %s -> %s %s %s %s",
            ConnectionName.CM,
            event.name,
            event.client_id,
            event.event_data.msg_id,
            ack_message.data.hex(" "),
            level=4,
        )
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
