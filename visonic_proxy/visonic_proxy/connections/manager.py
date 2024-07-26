"""Connection Manager."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
from enum import StrEnum
import logging

from .webserver import Webserver

from ..const import WATHCHDOG_TIMEOUT, Commands, ConnectionName

from .client import ClientConnection
from .server import ServerConnection


_LOGGER = logging.getLogger(__name__)


class ConnectionManagerStatus(StrEnum):
    """Connection manager status enum."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"


class ConnectionType(StrEnum):
    """Connection type enum."""

    SERVER = "server"
    CLIENT = "client"


@dataclass
class Forwarder:
    """Definition for a message forwarder."""

    destination: ConnectionName
    forward_to_all_connections: bool = False
    remove_pl31_wrapper: bool = False


@dataclass
class ConnectionProfile:
    """Connection Profile."""

    name: str
    connection_type: ConnectionType
    host: str
    port: int
    connect_with: ConnectionName | None = None
    ack_received_messages: bool = False
    send_keepalives: bool = False
    run_watchdog: bool = False
    preprocess: bool = False
    forwarders: list[Forwarder] | None = None
    track_acks: bool = False


@dataclass
class Connection:
    """Class to hold connection."""

    name: str
    connection: ClientConnection | ServerConnection
    keep_alive_timer_task: asyncio.Task = None


class ConnectionManager:
    """Coordinate message flow."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        received_message_callback: Callable,
        keep_alive_callback: Callable,
    ):
        """Init."""
        self._loop = loop
        self._cb_received_message = received_message_callback
        self._cb_keep_alive_trigger = keep_alive_callback
        self._connection_profiles: list[ConnectionProfile] = []
        self._connections: list[Connection] = []

        self.status: ConnectionManagerStatus = ConnectionManagerStatus.STOPPED

        self.webserver: Webserver = None
        self.watchdog_task: asyncio.Task = None
        self.webserver_task: asyncio.Task = None

    async def start(self):
        """Start Connection Manager"""

        _LOGGER.info("Starting Connection Manager")
        self.status = ConnectionManagerStatus.STARTING

        # Start HTTPS webserver
        if not self.webserver_task:
            _LOGGER.info("Starting Webserver")
            self.webserver = Webserver()
            self.webserver_task = self._loop.create_task(
                self.webserver.start(), name="Webserver"
            )
            # self.webserver_task.add_done_callback(webserver.stop())

        # Start watchdog timer
        if not self.watchdog_task:
            self.watchdog_task = self._loop.create_task(
                self.watchdog(), name="Watchdog timer"
            )
            _LOGGER.info("Started Watchdog Timer")

        # Start connections
        _LOGGER.debug("Starting Connections")
        await self.async_start_connections()

        self.status = ConnectionManagerStatus.RUNNING
        _LOGGER.info("Connection Manager Running")

    async def async_start_connections(self):
        """Start all connections that don't rely on connect_with."""
        if self.status not in [
            ConnectionManagerStatus.STARTING,
            ConnectionManagerStatus.RUNNING,
        ]:
            _LOGGER.error(
                "Connection manager is not running.  Unable to start connections."
            )
            return

        for profile in self._connection_profiles:
            if not profile.connect_with:
                _LOGGER.debug("Starting connection for %s", profile.name)
                await self.async_start_connection(profile)

    def add_connection(
        self, profile: ConnectionProfile, start_on_add: bool = True
    ) -> bool:
        """Add connection profile."""
        if not self.get_profile(profile.name):
            self._connection_profiles.append(profile)
            _LOGGER.debug("Added connection for %s", profile.name)
            if self.status == ConnectionManagerStatus.RUNNING:
                if start_on_add and not profile.connect_with:
                    _LOGGER.debug("Creating connection for %s", profile.name)
                    self._loop.create_task(
                        self.async_start_connection(profile),
                        name=f"Starting {profile.name}",
                    )
            return True
        _LOGGER.debug(
            "A connection profile with the name %s already exists", profile.name
        )
        return False

    def get_connection(
        self, connection_name: ConnectionName, client_id: str = ""
    ) -> Connection | None:
        """Return connection by name."""
        for connection in self._connections:
            if connection.name == connection_name:
                if client_id and isinstance(connection.connection, ClientConnection):
                    if connection.connection.parent_connection_id == client_id:
                        return connection
                elif client_id and isinstance(connection.connection, ServerConnection):
                    if connection.connection.clients:
                        return connection
                else:
                    return connection

    async def stop(self):
        """Shutdown all connections and terminate,"""
        self.status = ConnectionManagerStatus.CLOSING

        # Stop webserver
        if self.webserver_task and not self.webserver_task.done():
            _LOGGER.info("Stopping Webserver")
            try:
                await self.webserver.stop()
                self.webserver_task.cancel()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        # Stop watchdog
        if self.watchdog_task and not self.watchdog_task.done():
            _LOGGER.info("Stopping Watchdog")
            self.watchdog_task.cancel()

        for connection in self._connections:
            _LOGGER.debug("Shutting down %s", connection.connection.name)
            await connection.connection.shutdown()
        # Remove all connections
        self._connections.clear()
        self.status = ConnectionManagerStatus.STOPPED

    def get_connects_with(
        self, connection_name: ConnectionName
    ) -> list[ConnectionProfile]:
        """Returns list of connections that connect with connection name."""
        return [
            profile
            for profile in self._connection_profiles
            if profile.connect_with == connection_name
        ]

    def get_profile(self, name: ConnectionName) -> ConnectionProfile | None:
        """Get conneciton profile."""
        for profile in self._connection_profiles:
            if profile.name == name:
                return profile

    def is_connected(self, name: ConnectionName) -> bool:
        """Returns if a profile is connected."""
        connection = self.get_connection(name)
        if connection and connection.connection.connected:
            return True
        return False

    async def async_start_connection(
        self, profile: ConnectionProfile, parent_id: str = ""
    ):
        """Start connection."""
        if self.status not in [
            ConnectionManagerStatus.STARTING,
            ConnectionManagerStatus.RUNNING,
        ]:
            _LOGGER.error(
                "Connection manager is not running.  Unable to start connection %s",
                profile.name,
            )
            return

        if profile.connection_type == ConnectionType.CLIENT:
            connection = ClientConnection(
                profile.name,
                profile.host,
                profile.port,
                parent_id,
                self._handle_message,
                None,
                self._handle_disconnection,
                profile.run_watchdog,
            )
            await connection.connect()
        else:
            connection = ServerConnection(
                profile.name,
                profile.host,
                profile.port,
                self._handle_message,
                self._handle_client_connection,
                self._handle_disconnection,
                self._cb_keep_alive_trigger if profile.send_keepalives else None,
                profile.run_watchdog,
            )
            await connection.start_listening()
        self._connections.append(Connection(name=profile.name, connection=connection))

    async def async_stop_connection(
        self, connection_name: ConnectionName, client_id: str = ""
    ) -> bool:
        """Remove a conneciton by name.

        If connected, it will terminate the connection
        """
        for idx, connection in enumerate(self._connections):
            if connection.name == connection_name:
                if isinstance(connection.connection, ClientConnection):
                    if connection.connection.parent_connection_id == client_id:
                        await connection.connection.shutdown()
                        self._connections.pop(idx)
                        _LOGGER.info(
                            "%s %s connection removed.  Remaining connections: %s",
                            connection_name,
                            client_id,
                            [c.name for c in self._connections],
                        )
                        return True
                else:
                    await connection.connection.shutdown()
                    self._connections.pop(idx)
                    _LOGGER.info(
                        "%s %s connection removed.  Remaining connections: %s",
                        connection_name,
                        client_id,
                        [c.name for c in self._connections],
                    )
                    return True
        return False

    def _handle_client_connection(self, name: str, client_id: str):
        """Client connected to server callback."""
        # Process client connections that rely on another server connection
        # ie has a connect with
        if self.status != ConnectionManagerStatus.RUNNING:
            return

        # Start any connects with clients
        for profile in self.get_connects_with(name):
            self._loop.create_task(
                self.async_start_connection(profile, client_id),
                name=f"Starting {profile.name}",
            )

        _LOGGER.debug("CONNECTIONS: %s", self._connections)

    def _handle_message(self, source: ConnectionName, client_id: str, msg: bytes):
        """Handle message."""
        profile = self.get_profile(source)
        destinations = profile.forwarders

        # Handle special commands
        decoded_msg = msg.decode("ascii", errors="ignore")
        if decoded_msg in [c.name for c in list(Commands)]:
            self._cb_received_message(source, client_id, True, None, decoded_msg)
            # self._loop.create_task(self.shutdown())
        else:
            self._cb_received_message(source, client_id, False, destinations, msg)

    def send_message(self, destination: ConnectionName, client_id: str, msg: bytes):
        """Send message to named connection."""

        connection = self.get_connection(destination, client_id)
        if connection:
            connection.connection.send_message(client_id, msg)

    def _handle_disconnection(self, source: ConnectionName, client_id: str):
        """Handle disconnection."""
        # Get all connects with profiles and tear down
        if self.status != ConnectionManagerStatus.RUNNING:
            return

        profile = self.get_profile(source)
        connection = self.get_connection(source)

        if connection and isinstance(connection.connection, ClientConnection):
            # if connection is a client, disconnect the server client connection that started it
            if profile.connect_with:
                try:
                    connect_with = self.get_connection(profile.connect_with)
                    for client in connect_with.connection.clients:
                        if client == client_id:
                            _LOGGER.info(
                                "Requesting %s %s to disconnect",
                                profile.connect_with,
                                client_id,
                            )
                            connect_with.connection.disconnect_client(client_id)
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    _LOGGER.error(
                        "Exception disconnecting %s %s. %s",
                        connect_with.name,
                        client_id,
                        ex,
                    )

            # Remove this from connections list
            self._loop.create_task(
                self.async_stop_connection(profile.name, client_id),
                name=f"Removing {profile.name} {client_id} connection",
            )

        if connection and isinstance(connection.connection, ServerConnection):
            # if connection is a server, find what client connects with it and tear down
            connects_with = self.get_connects_with(source)
            for profile in connects_with:
                conn_with = self.get_connection(profile.name, client_id)
                if conn_with and conn_with.connection.connected:
                    _LOGGER.info(
                        "Requesting %s %s to disconnect", profile.name, client_id
                    )
                    self._loop.create_task(
                        self.async_stop_connection(profile.name, client_id),
                        name=f"Stop {profile.name} {client_id} connection",
                    )

    async def watchdog(self):
        """Disconnect non active connections.

        To be run in a task.
        """
        while True:
            # Runs every 10 seconds
            await asyncio.sleep(10)
            _LOGGER.debug("Running Watchdog")
            _LOGGER.debug("TASKS: %s", asyncio.all_tasks())
            # Look at server clients
            for connection in self._connections:
                if isinstance(connection.connection, ServerConnection):
                    if connection.connection.run_watchdog:
                        for client_id, client in connection.connection.clients.items():
                            _LOGGER.debug(
                                "Connection: %s, client_id: %s, last_received: %s, transport: %s",
                                connection.name,
                                client_id,
                                client.last_received_message,
                                client.transport,
                            )
                            if (
                                client.last_received_message
                                and dt.datetime.now() - client.last_received_message
                            ).total_seconds() > WATHCHDOG_TIMEOUT:
                                _LOGGER.info(
                                    "Watchdog disconnecting %s - %s due to inactivity",
                                    connection.name,
                                    client_id,
                                )
                                connection.connection.disconnect_client(client_id)
                if isinstance(connection.connection, ClientConnection):
                    if connection.connection.run_watchdog:
                        _LOGGER.debug(
                            "Connection: %s, client_id: %s, last_received: %s, transport: %s",
                            connection.name,
                            connection.connection.parent_connection_id,
                            connection.connection.last_received_message,
                            connection.connection.transport,
                        )
                        if (
                            connection.connection.last_received_message
                            and dt.datetime.now()
                            - connection.connection.last_received_message
                        ).total_seconds() > WATHCHDOG_TIMEOUT:
                            _LOGGER.info(
                                "Watchdog disconnecting %s - %s due to inactivity",
                                connection.name,
                                connection.connection.parent_connection_id,
                            )
                            await connection.connection.shutdown()
