"""Connection coordinator."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging

from ..builder import MessageBuilder, NonPowerLink31Message
from ..const import (
    MESSAGE_PORT,
    PROXY_MODE,
    SEND_E0_MESSAGES,
    VISONIC_HOST,
    VISONIC_RECONNECT_INTERVAL,
    ConnectionName,
    ConnectionStatus,
)
from ..decoders.pl31_decoder import PowerLink31Message
from ..events import Event, EventType, async_fire_event_later, subscribe
from ..helpers import log_message
from .client import ClientConnection
from .flow_manager import FlowManager
from .message import QueuedMessage
from .server import ServerConnection
from .webserver import Webserver

_LOGGER = logging.getLogger(__name__)


class ConnectionCoordinatorStatus(StrEnum):
    """Connection manager status enum."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"


@dataclass
class Connection:
    """Class to hold connection."""

    name: str
    connection: ServerConnection
    keep_alive_timer_task: asyncio.Task = None


class ConnectionCoordinator:
    """Coordinate message flow."""

    def __init__(
        self,
    ):
        """Init."""
        self._loop = asyncio.get_running_loop()
        self._connections: list[Connection] = []

        self.status: ConnectionCoordinatorStatus = ConnectionCoordinatorStatus.STOPPED

        self.webserver: Webserver = None
        self.watchdog_task: asyncio.Task = None
        self.webserver_task: asyncio.Task = None
        self.unsubscribe_events: list[Callable] = []

        self.alarm_server: ServerConnection = None
        self.monitor_server: ServerConnection = None
        self.visonic_clients: dict[str, ClientConnection] = {}

        self.flow_manager = FlowManager(self.send_message, self.is_connection_ready)

        self.initial_startup: bool = True

        self.connect_visonic: bool = PROXY_MODE
        self.download_mode: bool = False

    @property
    def is_disconnected_mode(self):
        """Return if no clients connected."""
        if self.initial_startup and PROXY_MODE:
            return False
        return self.alarm_server.disconnected_mode

    def set_disconnected_mode(self, disconnected: bool):
        """Set disconnected mode on Alarm server."""
        self.alarm_server.disconnected_mode = disconnected

    async def start(self):
        """Start Connection Manager."""

        log_message("Starting Connection Manager", level=1)
        self.status = ConnectionCoordinatorStatus.STARTING

        # Start HTTPS webserver
        if not self.webserver_task:
            log_message("Starting Webserver", level=1)
            self.webserver = Webserver()
            self.webserver_task = self._loop.create_task(
                self.webserver.start(), name="Webserver"
            )

        # Start connections
        _LOGGER.debug("Starting listener connections")
        await self.async_start_listener_connections()

        # Subscribe to events
        self.unsubscribe_events.extend(
            [
                subscribe(
                    ConnectionName.VISONIC,
                    EventType.WEB_REQUEST_CONNECT,
                    self.visonic_connect_request_event,
                ),
                subscribe(
                    ConnectionName.VISONIC,
                    EventType.REQUEST_CONNECT,
                    self.visonic_connect_request_event,
                ),
                subscribe("ALL", EventType.CONNECTION, self.connection_event),
                subscribe("ALL", EventType.DISCONNECTION, self.disconnection_event),
            ]
        )

        self.status = ConnectionCoordinatorStatus.RUNNING
        log_message("Connection Manager Running", level=1)

    async def stop(self):
        """Shutdown all connections and terminate."""
        self.status = ConnectionCoordinatorStatus.CLOSING

        # Unsubscribe all events
        if self.unsubscribe_events:
            for unsub in self.unsubscribe_events:
                unsub()

        # Stop flow manager
        await self.flow_manager.shutdown()

        # Stop webserver
        if self.webserver_task and not self.webserver_task.done():
            log_message("Stopping Webserver", level=1)
            try:
                await self.webserver.stop()
                self.webserver_task.cancel()
                while not self.webserver_task.done():
                    await asyncio.sleep(0.01)
            except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                pass

        # Stop clients
        for client in self.visonic_clients.values():
            await client.shutdown()
        self.visonic_clients.clear()

        # Stop connection servers
        await self.monitor_server.shutdown()
        await self.alarm_server.shutdown()

        self.status = ConnectionCoordinatorStatus.STOPPED

    async def async_start_listener_connections(self):
        """Start connection."""
        if self.status not in [
            ConnectionCoordinatorStatus.STARTING,
            ConnectionCoordinatorStatus.RUNNING,
        ]:
            _LOGGER.error(
                "Connection manager is not running.  Unable to start listener servers"
            )
            return

        self.alarm_server = ServerConnection(
            name=ConnectionName.ALARM,
            host="0.0.0.0",
            port=5001,
            data_received_callback=self.flow_manager.data_received,
            run_keepalive=False,
            run_watchdog=True,
            send_non_pl31_messages=False,
        )
        self.monitor_server = ServerConnection(
            name=ConnectionName.ALARM_MONITOR,
            host="0.0.0.0",
            port=5002,
            data_received_callback=self.flow_manager.data_received,
            run_keepalive=False,
            run_watchdog=False,
            send_non_pl31_messages=True,
        )
        await self.alarm_server.start_listening()
        await self.monitor_server.start_listening()

    async def start_client_connection(self, client_id: str):
        """Start client connection."""
        if self.status not in [
            ConnectionCoordinatorStatus.STARTING,
            ConnectionCoordinatorStatus.RUNNING,
        ]:
            _LOGGER.error(
                "Connection manager is not running.  Unable to start client connections"
            )
            return

        visonic_client = ClientConnection(
            name=ConnectionName.VISONIC,
            host=VISONIC_HOST,
            port=MESSAGE_PORT,
            parent_connection_id=client_id,
            data_received_callback=self.flow_manager.data_received,
            run_watchdog=True,
        )
        self.visonic_clients[client_id] = visonic_client

        # Register pending connection in flowmanger to hold any incomming messages for this
        # connection until connected
        self.flow_manager.register_connection(
            ConnectionName.VISONIC, client_id, ConnectionStatus.CONNECTING
        )

        await visonic_client.connect()

    async def stop_client_connection(self, client_id: str):
        """Terminate a client connection."""
        if client_id in self.visonic_clients:
            visonic_client = self.visonic_clients[client_id]
            if visonic_client.connected:
                await visonic_client.shutdown()
            del self.visonic_clients[client_id]

    async def visonic_connect_request_event(self, event: Event):
        """Handle connection event."""
        # If web request we wont get a client_id.  Get client id from first alarm client
        if not event.client_id:
            client_id = self.alarm_server.get_first_client_id()
        else:
            client_id = event.client_id

        if client_id and client_id not in self.visonic_clients and self.connect_visonic:
            log_message("Connecting Visonic Client %s", client_id, level=1)
            await self.start_client_connection(client_id)

    async def set_download_mode(self, enable: bool = False):
        """Disconnect Visonic and don't let reconnect for 5 mins.

        This is experimental to see if allows HA integration to load
        without too much interuption.
        """
        client_id = self.alarm_server.get_first_client_id()
        self.download_mode = enable
        if enable:
            _LOGGER.info("Setting Download Mode")
            # Stop any connecting to Visonic
            self.connect_visonic = False

            # If Visonic connected, disconnect it
            client_id = self.alarm_server.get_first_client_id()
            if self.visonic_clients.get(client_id):
                await self.stop_client_connection(client_id)

        else:
            _LOGGER.info("Exiting Download Mode")
            self.connect_visonic = True
            # Set reconnection timed event for Visonic
            event = Event(
                name=ConnectionName.VISONIC, event_type=EventType.REQUEST_CONNECT
            )
            await async_fire_event_later(3, event)

    async def connection_event(self, event: Event):
        """Handle connection event."""
        log_message("Connection event - %s", event, level=6)

        # Register connection with flow manager
        non_pl31_messages = event.event_data and event.event_data.get(
            "send_non_pl31_messages"
        )
        self.flow_manager.register_connection(
            event.name,
            event.client_id,
            ConnectionStatus.CONNECTED,
            send_non_pl31_messages=non_pl31_messages,
        )

        # Send status message on all disconnection events
        if self.monitor_server.clients:
            await self.send_status_message(
                ConnectionName.ALARM_MONITOR, self.monitor_server.get_first_client_id()
            )

        if event.name == ConnectionName.ALARM:
            self.webserver.unset_request_to_connect()
            if self.connect_visonic:
                await self.visonic_connect_request_event(event)

        elif event.name == ConnectionName.VISONIC:
            self.set_disconnected_mode(False)

            # Initiate messages to send if first connection to Visonic
            if not self.initial_startup:
                if len(self.visonic_clients) == 1:
                    init_messages = [
                        ("b0 17 51 51 51 0f 24", ConnectionName.ALARM),
                        # ("b0 17 51", ConnectionName.ALARM),
                        # ("b0 17 51", ConnectionName.ALARM),
                        # ("b0 17 0f", ConnectionName.ALARM),
                        # ("b0 17 51", ConnectionName.ALARM),
                    ]
                    for init_message in init_messages:
                        message = MessageBuilder().message_preprocessor(
                            bytes.fromhex(init_message[0]),
                        )
                        await self.queue_message(
                            ConnectionName.CM,
                            0,
                            ConnectionName.ALARM,
                            event.client_id,
                            message,
                        )
                        await asyncio.sleep(0.1)
            else:
                self.initial_startup = False

    async def disconnection_event(self, event: Event):
        """Handle connection event."""
        log_message("Disconnection event - %s", event, level=6)

        # Unregister connection with flow manager
        self.flow_manager.unregister_connection(event.name, event.client_id)

        # Send status message on all disconnection events
        if self.monitor_server.clients:
            await self.send_status_message(
                ConnectionName.ALARM_MONITOR, self.monitor_server.get_first_client_id()
            )

        if event.name == ConnectionName.ALARM:
            # Set webserver to reconnect if no clients
            if self.alarm_server.client_count == 0:
                self.webserver.set_request_to_connect()

            # If Alarm disconnects, disconnect Visonic
            # Note this can be a second alarm and Visonic connection
            await self.stop_client_connection(event.client_id)

        if event.name == ConnectionName.VISONIC:
            # Remove client connection reference
            await self.stop_client_connection(event.client_id)

            if len(self.visonic_clients) == 0:
                self.set_disconnected_mode(True)

                # Set reconnection timed event for Visonic
                event = Event(
                    name=ConnectionName.VISONIC, event_type=EventType.REQUEST_CONNECT
                )
                await async_fire_event_later(VISONIC_RECONNECT_INTERVAL, event)

    async def send_status_message(self, destination: ConnectionName, client_id: str):
        """Send an status message.

        Used to allow management of this Connection Manager from the Monitor Connection
        """
        # Alarm connection status
        if SEND_E0_MESSAGES:
            alarm_status = len(self.alarm_server.clients)
            visonic_status = len(self.visonic_clients)
            monitor_status = len(self.monitor_server.clients)

            message_queue = self.flow_manager.sender_queue.qsize()

            msg = f"e0 {alarm_status:02x} {visonic_status:02x} {monitor_status:02x} {message_queue:02x} 43"
            message = MessageBuilder().message_preprocessor(bytes.fromhex(msg))
            await self.queue_message(
                ConnectionName.CM,
                0,
                destination,
                client_id,
                message,
                requires_ack=False,
            )

    def is_connection_ready(self, message: QueuedMessage) -> bool:
        """Return if connection ready to send."""
        if message.destination == ConnectionName.ALARM:
            return len(self.alarm_server.clients) > 0

        if message.destination == ConnectionName.ALARM_MONITOR:
            return len(self.monitor_server.clients) > 0
        if message.destination == ConnectionName.VISONIC:
            return len(self.visonic_clients) > 0

    async def send_message(self, message: QueuedMessage):
        """Route message to correct connection."""

        if message.destination == ConnectionName.ALARM:
            result = await self.alarm_server.send_message(message)
        elif message.destination == ConnectionName.ALARM_MONITOR:
            result = await self.monitor_server.send_message(message)
        elif message.destination == ConnectionName.VISONIC:
            if self.visonic_clients:
                try:
                    client = self.visonic_clients[message.destination_client_id]
                    result = await client.send_message(message)
                except KeyError:
                    _LOGGER.warning(
                        "Visonic client %s is not connected.  Dumping message send request",
                        message.destination_client_id,
                    )
                    result = False
        return result

    async def queue_message(
        self,
        source: ConnectionName,
        source_client_id,
        destination: ConnectionName,
        destination_client_id: str,
        message: PowerLink31Message | NonPowerLink31Message,
        requires_ack: bool = True,
    ):
        """Route message to flow manager."""
        await self.flow_manager.queue_message(
            source,
            source_client_id,
            destination,
            destination_client_id,
            message,
            requires_ack,
        )
