"""Connection coordinator."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging

from ..builder import MessageBuilder
from ..const import MESSAGE_PORT, VISONIC_HOST, ConnectionName, ConnectionSourcePriority
from ..events import Event, EventType, async_fire_event_later, subscribe
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

    @property
    def is_disconnected_mode(self):
        """Return if no clients connected."""
        return self.alarm_server.disconnected_mode

    def set_disconnected_mode(self, disconnected: bool):
        """Set disconnected mode on Alarm server."""
        self.alarm_server.disconnected_mode = disconnected

    async def start(self):
        """Start Connection Manager."""

        _LOGGER.info("Starting Connection Manager")
        self.status = ConnectionCoordinatorStatus.STARTING

        # Start HTTPS webserver
        if not self.webserver_task:
            _LOGGER.info("Starting Webserver")
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
        _LOGGER.info("Connection Manager Running")

    async def stop(self):
        """Shutdown all connections and terminate."""
        self.status = ConnectionCoordinatorStatus.CLOSING

        # Unsubscribe all events
        if self.unsubscribe_events:
            for unsub in self.unsubscribe_events:
                unsub()

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
            ConnectionName.ALARM, "0.0.0.0", 5001, True, True
        )
        self.monitor_server = ServerConnection(
            ConnectionName.ALARM_MONITOR, "0.0.0.0", 5002, False, False
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
            ConnectionName.VISONIC, VISONIC_HOST, MESSAGE_PORT, client_id, True
        )
        self.visonic_clients[client_id] = visonic_client
        await visonic_client.connect()

    async def stop_client_connection(self, client_id: str):
        """Terminate a client connection."""
        if client_id in self.visonic_clients:
            visonic_client = self.visonic_clients[client_id]
            await visonic_client.shutdown()
            del self.visonic_clients[client_id]

    async def visonic_connect_request_event(self, event: Event):
        """Handle connection event."""
        # If web request we wont get a client_id.  Get client id from first alarm client
        if not event.client_id:
            client_id = self.alarm_server.get_first_client_id()
        else:
            client_id = event.client_id

        if client_id and client_id not in self.visonic_clients:
            _LOGGER.info("Connecting Visonic Client")
            await self.start_client_connection(client_id)

    async def connection_event(self, event: Event):
        """Handle connection event."""
        _LOGGER.info("Connection event - %s", event)
        if event.name == ConnectionName.ALARM:
            await self.visonic_connect_request_event(event)

        if event.name == ConnectionName.VISONIC:
            self.set_disconnected_mode(False)

            # Request a 0f message from the alarm
            message = MessageBuilder().message_preprocessor(1, bytes.fromhex("b0 0f"))
            await self.send_message(
                ConnectionName.CM,
                ConnectionName.ALARM,
                event.client_id,
                message.msg_id,
                message.msg_data,
            )

    async def disconnection_event(self, event: Event):
        """Handle connection event."""
        _LOGGER.info("Disconnection event - %s", event)

        if event.name == ConnectionName.VISONIC and not self.visonic_clients:
            self.set_disconnected_mode(True)

            # Set reconnection in KEEPALIVE timeout
            event = Event(ConnectionName.VISONIC, EventType.REQUEST_CONNECT)
            self._loop.create_task(
                async_fire_event_later(10, event),
                name="Visonic Reconnect Event",
            )

    async def send_message(
        self,
        source: ConnectionName,
        destination: ConnectionName,
        client_id: str,
        message_id: int,
        message: bytes,
    ):
        """Route message to correct connection."""
        priority = ConnectionSourcePriority[source.name]

        if destination == ConnectionName.ALARM:
            result = await self.alarm_server.queue_message(
                priority, client_id, message_id, message
            )
        if destination == ConnectionName.ALARM_MONITOR:
            result = await self.monitor_server.queue_message(
                priority, client_id, message_id, message
            )
        if destination == ConnectionName.VISONIC:
            if self.visonic_clients:
                try:
                    client = self.visonic_clients[client_id]
                    result = await client.queue_message(priority, message_id, message)
                except KeyError:
                    _LOGGER.warning(
                        "Visonic client %s is not connected.  Dumping message send request",
                        client_id,
                    )
                    result = False
        return result
