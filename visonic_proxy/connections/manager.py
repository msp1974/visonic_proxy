"""Connection coordinator."""

import asyncio
from collections.abc import Callable
import datetime as dt
from enum import StrEnum
import logging

from ..const import Config
from ..enums import (
    ConnectionName,
    ConnectionPriority,
    ConnectionStatus,
    Mode,
    MsgLogLevel,
)
from ..events import ALL_CLIENTS, Event, EventType
from ..flow_manager import FlowManager
from ..message import QueuedMessage
from ..proxy import Proxy
from .client import ClientConnection
from .server import ServerConnection
from .webserver import Webserver

_LOGGER = logging.getLogger(__name__)


class ConnectionCoordinatorStatus(StrEnum):
    """Connection manager status enum."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"


class ConnectionManager:
    """Coordinate message flow."""

    def __init__(self, proxy: Proxy):
        """Init."""
        self.proxy = proxy
        self.flow_manager = FlowManager(self.proxy)

        self.status: ConnectionCoordinatorStatus = ConnectionCoordinatorStatus.STOPPED

        self.webserver: Webserver = None
        self.webserver_task: asyncio.Task = None
        self.watchdog_task: asyncio.Task = None
        self.stealth_timeout_task: asyncio.Task = None

        self.servers: dict[str, ServerConnection] = {}

        self.unsubscribe_events: list[Callable] = []

        self.initial_startup: bool = True
        self.connect_visonic: bool = Config.PROXY_MODE

    @property
    def is_disconnected_mode(self):
        """Return if no clients connected."""
        if self.initial_startup and Config.PROXY_MODE:
            return False
        return self.proxy.status.disconnected_mode

    def set_disconnected_mode(self, disconnected: bool):
        """Set disconnected mode on Alarm server."""
        self.proxy.status.disconnected_mode = disconnected

    async def start(self):
        """Start Connection Manager."""

        _LOGGER.info("Starting Connection Manager")
        self.status = ConnectionCoordinatorStatus.STARTING

        # Start flow manager
        await self.flow_manager.start(self.send_message)

        # Start connections
        _LOGGER.debug("Starting listener connections")
        await self.async_start_listener_connections()

        # Subscribe to events
        self.unsubscribe_events.extend(
            [
                self.proxy.events.subscribe(
                    ConnectionName.VISONIC,
                    EventType.REQUEST_CONNECT,
                    self.client_connect_request,
                ),
                self.proxy.events.subscribe(
                    ALL_CLIENTS, EventType.CONNECTION, self.connection_event
                ),
                self.proxy.events.subscribe(
                    ConnectionName.CM, EventType.SET_MODE, self.set_mode
                ),
                self.proxy.events.subscribe(
                    ALL_CLIENTS, EventType.DISCONNECTION, self.disconnection_event
                ),
            ]
        )

        # Start HTTPS webserver
        if not self.webserver_task:
            _LOGGER.info("Starting Webserver")
            self.webserver = Webserver(self.proxy)
            self.webserver_task = self.proxy.loop.create_task(
                self.webserver.start(), name="Webserver"
            )

        self.status = ConnectionCoordinatorStatus.RUNNING
        _LOGGER.info("Connection Manager started")

    async def stop(self):
        """Shutdown all connections and terminate."""
        self.status = ConnectionCoordinatorStatus.CLOSING
        _LOGGER.info("Stopping Connection Manager")

        # Unsubscribe all events
        if self.unsubscribe_events:
            for unsub in self.unsubscribe_events:
                unsub()

        # Stop flow manager
        await self.flow_manager.stop()

        # Stop webserver
        if self.webserver_task and not self.webserver_task.done():
            _LOGGER.info("Stopping Webserver")
            try:
                await self.webserver.stop()
                self.webserver_task.cancel()
                while not self.webserver_task.done():
                    await asyncio.sleep(0.01)
            except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                pass

        # Stop clients
        for connection in self.proxy.clients.connections:
            for client in self.proxy.clients.get_clients(connection):
                connection: ClientConnection | ServerConnection = client.connection
                if isinstance(connection, ClientConnection):
                    await connection.shutdown()
                else:
                    connection.disconnect_client(client.id)

        # Stop connection servers
        for server in self.servers.values():
            await server.shutdown()

        # Cancel stealth timeout task
        if self.stealth_timeout_task and not self.stealth_timeout_task.done():
            self.stealth_timeout_task.cancel()

        self.status = ConnectionCoordinatorStatus.STOPPED
        _LOGGER.info("Connection Manager is stopped")

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

        # TODO: Change these to iterate over definitions from proxy.py
        self.servers[ConnectionName.ALARM] = ServerConnection(
            proxy=self.proxy,
            name=ConnectionName.ALARM,
            host="0.0.0.0",
            port=Config.MESSAGE_PORT,
            data_received_callback=self.flow_manager.data_received,
            run_keepalive=not Config.ALARM_MONITOR_SENDS_KEEPALIVES,
            run_watchdog=True,
            send_non_pl31_messages=False,
        )
        self.servers[ConnectionName.ALARM_MONITOR] = ServerConnection(
            proxy=self.proxy,
            name=ConnectionName.ALARM_MONITOR,
            host="0.0.0.0",
            port=Config.ALARM_MONITOR_PORT,
            data_received_callback=self.flow_manager.data_received,
            run_keepalive=False,
            run_watchdog=False,
            send_non_pl31_messages=True,
        )

        for server in self.servers.values():
            await server.start_listening()

    async def start_client_connection(self, client_id: int):
        """Start client connection."""
        if self.status not in [
            ConnectionCoordinatorStatus.STARTING,
            ConnectionCoordinatorStatus.RUNNING,
        ]:
            _LOGGER.error(
                "Connection manager is not running.  Unable to start client connections"
            )
            return

        _LOGGER.info(
            "Starting %s client connection for %s %s",
            ConnectionName.VISONIC,
            ConnectionName.ALARM,
            client_id,
            extra=MsgLogLevel.L1,
        )

        client = ClientConnection(
            proxy=self.proxy,
            name=ConnectionName.VISONIC,
            host=Config.VISONIC_HOST,
            port=Config.MESSAGE_PORT,
            parent_connection_id=client_id,
            data_received_callback=self.flow_manager.data_received,
            run_watchdog=True,
        )

        # Register pending connection in flowmanger to hold any incomming messages for this
        # connection until connected
        self.proxy.clients.add(
            ConnectionName.VISONIC,
            client_id,
            client,
            ConnectionStatus.CONNECTING,
            connection_priority=ConnectionPriority[ConnectionName.VISONIC.name],
            send_non_pl31_messages=False,
        )

        self.set_disconnected_mode(False)

        await client.connect()

    async def stop_client_connection(self, client_id: int):
        """Terminate a client connection."""
        if connection_info := self.proxy.clients.get_client(
            ConnectionName.VISONIC, client_id
        ):
            connection: ClientConnection | ServerConnection = connection_info.connection
            if connection.connected:
                await connection.shutdown()

            self.proxy.clients.remove(ConnectionName.VISONIC, client_id)

    async def client_connect_request(self, event: Event):
        """Handle connection event."""
        # If web request we wont get a client_id.  Get client id from first alarm client
        if not self.proxy.status.stealth_mode:
            if not event.client_id:
                # Check we have an Alarm connected
                if connection_info := self.proxy.clients.get_first_client(
                    ConnectionName.ALARM
                ):
                    event.client_id = connection_info.id

            if event.client_id and not self.proxy.clients.get_client(
                ConnectionName.VISONIC, event.client_id
            ):
                # Ensure we have an Alarm connection and not an existing Visonic one that matches
                _LOGGER.debug("Connecting Visonic Client %s", event.client_id)
                await self.start_client_connection(event.client_id)

    async def set_mode(self, event: Event):
        """Set modes via events.

        mode is the data key
        setting is the data value
        """
        if Mode.STEALTH in event.event_data:
            await self.set_stealth_mode(event.event_data[Mode.STEALTH])

    async def set_stealth_mode(self, enable: bool = False):
        """Disconnect Visonic and don't let reconnect for 5 mins.

        This is experimental to see if allows HA integration to load
        without too much interuption.
        """
        if enable and not self.proxy.status.stealth_mode:
            _LOGGER.info("Entering Stealth Mode", extra=MsgLogLevel.L1)
            # Stop any connecting to Visonic
            self.proxy.status.stealth_mode = True
            self.connect_visonic = False

            # If Visonic connected, disconnect it
            if self.proxy.clients.count(ConnectionName.VISONIC) > 0:
                client_id = self.servers[ConnectionName.ALARM].get_first_client_id()
                if self.proxy.clients.get_client(ConnectionName.VISONIC, client_id):
                    await self.stop_client_connection(client_id)

            # Set timeout task.  This is a safety net to reconnect Visonic if Monitor connection does not release
            # stealth mode and does not keep requesting.
            self.stealth_timeout_task = self.proxy.loop.create_task(
                self.stealth_mode_timeout()
            )

        elif (not enable) and self.proxy.status.stealth_mode:
            # If cause by timeout
            _LOGGER.info("Exiting Stealth Mode", extra=MsgLogLevel.L1)

            # Stop any timeout task
            if self.stealth_timeout_task and not self.stealth_timeout_task.done():
                self.stealth_timeout_task.cancel()

            self.proxy.status.stealth_mode = False
            if Config.PROXY_MODE:
                self.connect_visonic = True

                # Set initial load to false in case Stealth was activated before first connection
                self.initial_startup = False

                # Set reconnection timed event for Visonic
                event = Event(
                    name=ConnectionName.VISONIC, event_type=EventType.REQUEST_CONNECT
                )
                self.proxy.events.fire_event_later(1, event)

    async def stealth_mode_timeout(self):
        """Timeout for stealth mode to revert if no message from HA."""
        activity = True
        while activity:
            await asyncio.sleep(1)
            active_clients = [
                (dt.datetime.now() - client.last_received).total_seconds()
                <= Config.STEALTH_MODE_TIMEOUT
                for client in self.proxy.clients.get_clients(
                    ConnectionName.ALARM_MONITOR
                )
            ]

            if True not in active_clients:
                activity = False
                # Log timeout message if exit caused by timeout timer
                _LOGGER.info("Timeout in Stealth Mode", extra=MsgLogLevel.L1)
                self.proxy.events.fire_event(
                    Event(
                        name=ConnectionName.CM,
                        event_type=EventType.SET_MODE,
                        event_data={Mode.STEALTH: False, "timeout": True},
                    )
                )

    async def connection_event(self, event: Event):
        """Handle connection event."""
        _LOGGER.debug("CONNECTION EVENT: %s", event)

        # Register connection with flow manager
        connection = event.event_data and event.event_data.get("connection")
        non_pl31_messages = event.event_data and event.event_data.get(
            "send_non_pl31_messages"
        )

        # Register client connection
        self.proxy.clients.add(
            name=event.name,
            client_id=event.client_id,
            connection=connection,
            connection_status=ConnectionStatus.CONNECTED,
            connection_priority=ConnectionPriority[event.name.name],
            send_non_pl31_messages=non_pl31_messages,
        )

        # If flow manager was waiting for a pending connection, release
        # the wait lock
        if not self.flow_manager.pending_has_connected.is_set():
            self.flow_manager.pending_has_connected.set()

        if event.name == ConnectionName.ALARM:
            self.webserver.unset_request_to_connect()
            if self.connect_visonic:
                await self.client_connect_request(event)

        elif event.name == ConnectionName.VISONIC:
            self.set_disconnected_mode(False)
            self.proxy.clients.update_status(
                event.name, event.client_id, ConnectionStatus.CONNECTED
            )

            # Send initiation messages to Visonic
            if (
                not self.initial_startup
                and self.proxy.clients.count(ConnectionName.VISONIC) == 1
                # Test Alarm clients also as if 2, this Visonic connection is for ADM-CID
                # In which case do not send
                and self.proxy.clients.count(ConnectionName.ALARM) == 1
            ):
                await (
                    self.flow_manager.message_router.command_manager.send_init_message()
                )
            else:
                self.initial_startup = False

        # Send status message to Alarm Monitor
        if (
            Config.SEND_E0_MESSAGES
            and self.proxy.clients.count(ConnectionName.ALARM_MONITOR) > 0
        ):
            await self.flow_manager.message_router.command_manager.send_status_message()

    async def disconnection_event(self, event: Event):
        """Handle connection event."""
        _LOGGER.debug("Received Disconnection Event - %s", event)

        # Unregister client connection
        self.proxy.clients.remove(event.name, event.client_id)

        # Send status message to Alarm Monitor
        if (
            Config.SEND_E0_MESSAGES
            and self.proxy.clients.count(ConnectionName.ALARM) > 0
        ):
            await self.flow_manager.message_router.command_manager.send_status_message()

        if event.name == ConnectionName.ALARM:
            # Set webserver to reconnect if no clients
            if self.proxy.clients.count(event.name) == 0:
                self.webserver.set_request_to_connect()

            # If Alarm disconnects, disconnect Visonic
            # Note this can be a second alarm and Visonic connection
            await self.stop_client_connection(event.client_id)

        if event.name == ConnectionName.VISONIC:
            # Remove client connection reference
            await self.stop_client_connection(event.client_id)

            if self.proxy.clients.count(event.name) == 0:
                self.set_disconnected_mode(True)

                # Set reconnection timed event for Visonic
                event = Event(
                    name=ConnectionName.VISONIC, event_type=EventType.REQUEST_CONNECT
                )
                self.proxy.events.fire_event_later(
                    Config.VISONIC_RECONNECT_INTERVAL, event
                )

    async def send_message(self, message: QueuedMessage):
        """Route message to correct connection."""

        connection_info = None
        if message.destination_client_id == 0:
            # This will be a CM generated message or a Alarm Monitor connection message.
            # Select the first connection of type
            connection_info = self.proxy.clients.get_first_client(message.destination)
        else:
            connection_info = self.proxy.clients.get_client(
                message.destination, message.destination_client_id
            )

        if connection_info:
            # We have a valid connection info record
            try:
                connection: ClientConnection | ServerConnection = (
                    connection_info.connection
                )
                await connection.send_message(message)

            except Exception as ex:  # noqa: BLE001
                _LOGGER.error(
                    "Error sending message to %s %s: %s",
                    connection_info.name,
                    connection_info.id,
                    ex,
                )
