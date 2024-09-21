"""Message coordinator."""

from collections.abc import Callable
from enum import StrEnum
import logging

from visonic_proxy.proxy import Proxy
from visonic_proxy.transcoders.b0_basic_decoder import B0BasicDecoder

from ..const import (
    ADM_ACK,
    ADM_CID,
    NAK,
    VIS_ACK,
    VIS_BBA,
    Config,
    ConnectionName,
    ManagedMessages,
    ManagerStatus,
    Mode,
    MsgLogLevel,
)
from ..events import Event, EventType
from ..message import RoutableMessage
from .command_manager import CommandManager
from .message_filter import is_filtered

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

    def __init__(self, proxy: Proxy):
        """Init."""
        self.proxy = proxy
        self.status: MessageCoordinatorStatus = MessageCoordinatorStatus.STOPPED
        self.cb_send_message: Callable

        self.command_manager = CommandManager(self.proxy)

        self._unsubscribe_listeners: list[Callable] = []

    async def start(self, send_message_callback: Callable):
        """Start message coordinator."""

        self.cb_send_message = send_message_callback

        self.command_manager.start(self.cb_send_message)

        self.status = MessageCoordinatorStatus.RUNNING
        _LOGGER.info("Message Router started")

    async def stop(self):
        """Stop message coordinator."""
        _LOGGER.debug("Stopping Message Coordinator")
        self.status = ManagerStatus.CLOSING

        await self.command_manager.stop()

        for unsub in self._unsubscribe_listeners:
            unsub()

        self.status = ManagerStatus.STOPPED
        _LOGGER.info("Message Router stopped")

    async def process_message(self, message: RoutableMessage):
        """Update status from certain messages."""
        if message.message.message_class == "b0":
            b0_command = message.message.data[3:4].hex()

            if b0_command in ["0f", "24"]:
                # These are status messages and we can get if in download mode
                status = B0BasicDecoder().decode(message.message.data)
                is_download_mode = status.get("status", "") == 7
                if self.proxy.status.download_mode != is_download_mode:
                    self.proxy.status.download_mode = is_download_mode
                    await self.command_manager.send_status_message()

            if b0_command == "51" and self.proxy.status.disconnected_mode:
                # Get all the commands in a b0 51 message and add to init commands if we are
                # in disconnected mode.  Then when we reconnect Visonic, we will send them.
                if commands := B0BasicDecoder().decode(message.message.data):
                    self.command_manager.init_commands.extend(
                        commands.get("commands", [])
                    )

        # Handle non b0 messaged
        # 09 is download mode request, 0f is exit download mode, 3c is message when in download mode after request
        # No such confirmation for a 0f
        if message.message.message_class in ["3c", "0f"]:
            self.proxy.status.download_mode = message.message.message_class == "3c"
            await self.command_manager.send_status_message()

    async def route_message(self, route_message: RoutableMessage):
        """Route message."""
        _LOGGER.debug("ROUTE MESSAGE: %s", route_message)

        if route_message.message.msg_type in [VIS_ACK, ADM_ACK, NAK]:
            await self.route_ack(route_message)
        else:
            name = ConnectionName(route_message.source).name
            func = f"{name.lower()}_router"
            if hasattr(self, func):
                await getattr(self, func)(route_message)

    async def route_ack(self, message: RoutableMessage):
        """Handle data received event."""

        # Event data should be a PowerLink31Message or NonPowerLink31Message (from Alarm Monitor)

        # ---------------------------------------------------------------
        # ALARM
        # ---------------------------------------------------------------
        if message.source == ConnectionName.ALARM:
            # If we have no destination, ie we were not expecting it and from Alarm
            # If we are not in disconnected mode, send it to Visonic
            if not message.destination and not self.proxy.status.disconnected_mode:
                await self.forward_message(
                    ConnectionName.VISONIC, message.source_client_id, message
                )
                return

        # ---------------------------------------------------------------
        # VISONIC
        # ---------------------------------------------------------------
        if message.source == ConnectionName.VISONIC:
            await self.forward_message(
                ConnectionName.ALARM, message.source_client_id, message
            )
            return

        # ---------------------------------------------------------------
        # ALARM MONITOR
        # ---------------------------------------------------------------
        # if message.source == ConnectionName.ALARM_MONITOR:
        #    if self.proxy.status.disconnected_mode:
        #        # Must be for Alarm
        #        await self.forward_message(
        #            ConnectionName.ALARM,
        #            0,
        #            message,
        #            False,
        #        )
        #    return

        # ---------------------------------------------------------------
        # ALL
        # ---------------------------------------------------------------

        if message.destination and message.destination_client_id:
            # If it is an ACK, we expect to have destination and desitnation_client_id
            # If we don't, just dump it
            await self.forward_message(
                message.destination, message.destination_client_id, message
            )
            return

        if (
            message.destination != ConnectionName.CM
            and message.source != ConnectionName.ALARM_MONITOR
        ):
            _LOGGER.debug("ACK received with no destination. %s", message)

        return

    async def alarm_router(self, message: RoutableMessage):
        """Route Alarm received VIS-BBA and *ADM-CID messages."""

        if (
            self.proxy.clients.count(ConnectionName.ALARM_MONITOR) > 0
            and message.message.msg_type != ADM_CID
        ):
            # Set things going to Alarm Monitor that do not need ACKs
            requires_ack = False
            if (
                message.message.message_class == "b0"
                or message.message.data
                == bytes.fromhex(ManagedMessages.OUT_OF_DOWNLOAD_MODE)
                or not Config.ALARM_MONITOR_SENDS_ACKS
            ):
                requires_ack = False

            await self.forward_message(
                ConnectionName.ALARM_MONITOR,
                0,
                message,
                requires_ack=requires_ack,
            )

        if not self.proxy.status.disconnected_mode:
            await self.forward_message(
                ConnectionName.VISONIC, message.source_client_id, message
            )

        # Does CM send an ACK?
        if self.proxy.status.disconnected_mode and message.message.msg_type == VIS_BBA:
            await self.command_manager.send_ack_message(message)

        # Process information from certain messages
        await self.process_message(message)

    async def visonic_router(self, message: RoutableMessage):
        """Route Visonic received VIS-BBA and *ADM-CID messages."""

        if message.message.data.hex(" ") == ManagedMessages.DISCONNECT_MESSAGE:
            # Manage the disconnect message comming from Visonic to the Alarm
            # Do not forward to Alarm, but send ACK back to Visonic and then request
            # a disconnect for the Visonic connection.

            _LOGGER.info(
                "%s %s requested to disconnect",
                message.source,
                message.source_client_id,
                extra=MsgLogLevel.L1,
            )
            await self.command_manager.send_ack_message(message)

            # Send disconnection request event which will be picked up
            # by connection manager and disconnect this connection
            self.proxy.events.fire_event(
                Event(
                    name=message.source,
                    event_type=EventType.REQUEST_DISCONNECT,
                    client_id=message.source_client_id,
                )
            )

            # As we do not forward this disconnect message to the Alarm in order to keep it
            # connected, we need to send something to the Alarm to keep the message IDs in sync.
            # So, send a KEEPALIVE message to do this.
            self.proxy.events.fire_event(
                Event(
                    name=ConnectionName.ALARM,
                    event_type=EventType.SEND_KEEPALIVE,
                    client_id=message.source_client_id,
                )
            )
        else:
            # Forward all non managed messages to the Alarm connection
            await self.forward_message(
                ConnectionName.ALARM, message.source_client_id, message
            )

    async def alarm_monitor_router(self, message: RoutableMessage):
        """Route Alarm Monitor received VIS-BBA messages.

        Will receive NonPowerLink31Message in event_data
        """
        # Respond to command requests
        if message.message.message_class == Config.ACTION_COMMAND.lower():
            if Config.ALARM_MONITOR_NEEDS_ACKS:
                await self.command_manager.send_ack_message(message)
            await self.command_manager.do_action_command(message)
            return

        # Set DOWNLOAD mode
        # TODO: Dont fix this message class here!!
        if (
            message.message.data == bytes.fromhex(ManagedMessages.DOWNLOAD)
            or message.message.message_class == "24"
        ):
            # Alarm Monitor has requested to download EPROM.  Need to ask connection manager to
            # set stealth mode
            if not self.proxy.status.stealth_mode:
                _LOGGER.info("Entering download mode", extra=MsgLogLevel.L1)
                self.proxy.events.fire_event(
                    Event(
                        name=ConnectionName.CM,
                        event_type=EventType.SET_MODE,
                        event_data={Mode.STEALTH: True},
                    )
                )

        # Unset DOWNLOAD mode
        if message.message.data == bytes.fromhex(ManagedMessages.EXIT_DOWNLOAD_MODE):
            # Alarm Monitor has requested to end downloading EPROM.  Need to ask connection manager to
            # unset stealth mode
            if self.proxy.status.stealth_mode:
                _LOGGER.info("Exiting download mode", extra=MsgLogLevel.L1)
                self.proxy.events.fire_event(
                    Event(
                        name=ConnectionName.CM,
                        event_type=EventType.SET_MODE,
                        event_data={Mode.STEALTH: False},
                    )
                )

        # Filter messages from being sent to Alarm
        if is_filtered(message.message.data):
            _LOGGER.info("Not sending message due to filter", extra=MsgLogLevel.L2)
            if Config.ALARM_MONITOR_NEEDS_ACKS:
                await self.command_manager.send_ack_message(message)
            return

        # Forward message to Alarm
        await self.forward_message(ConnectionName.ALARM, 0, message, requires_ack=True)

    async def forward_message(
        self,
        destination: ConnectionName,
        destination_client_id: int,
        message: RoutableMessage,
        requires_ack: bool = True,
    ):
        """Forward message to destination.

        If desintation client id is 0, CM will forward to first connection with that name
        """
        message.destination = destination
        message.destination_client_id = destination_client_id

        # Set some overides here for known messages that do not get ACKd
        if (
            message.destination
            == (ConnectionName.ALARM_MONITOR and not Config.ALARM_MONITOR_SENDS_ACKS)
            or message.message.data.hex(" ") in Config.NO_WAIT_FOR_ACK_MESSAGES
        ):
            requires_ack = False

        _LOGGER.debug(
            "Forwading Message: %s -> %s %s %s - %s",
            message.source,
            destination,
            message.source_client_id,
            message.message.msg_id,
            message.message.data.hex(" "),
        )

        await self.cb_send_message(
            message,
            requires_ack=requires_ack,
        )
