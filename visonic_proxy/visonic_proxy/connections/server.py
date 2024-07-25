"""Handles listening ports for clients to connect to."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime as dt
import logging
from socket import AF_INET

from ..const import KEEPALIVE_TIMER
from .protocol import ConnectionProtocol

_LOGGER = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """Class to hold client connections."""

    transport: asyncio.Transport
    last_received_message: dt.datetime | None = None
    last_sent_message: dt.datetime | None = None


class ServerConnection:
    """Handles device connecting to us."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        received_message_callback: Callable,
        connected_callback: Callable = None,
        disconnected_callback: Callable = None,
        keep_alive_callback: Callable = None,
        run_watchdog: bool = False,
    ):
        """Init."""
        self.loop = asyncio.get_running_loop()
        self.name = name
        self.host = host
        self.port = port

        self.cb_received = received_message_callback
        self.cb_connected = connected_callback
        self.cb_disconnected = disconnected_callback
        self.cb_keep_alive = keep_alive_callback
        self.run_watchdog = run_watchdog

        self.server = None
        self.clients: dict[str, ClientConnection] = {}

        self.keep_alive_timer_task: asyncio.Task = None

    @property
    def client_count(self):
        """Get count of clients"""
        return len(self.clients.keys())

    def get_client_id(self, transport: asyncio.Transport) -> str:
        """Generate client_id."""
        return f"P{transport.get_extra_info('peername')[1]}"

    def get_transport(self, client_id: str) -> asyncio.Transport | None:
        """Get client transport."""
        try:
            return self.clients[client_id].transport
        except KeyError:
            return None

    async def start_listening(self):
        """Start server to allow Alarm to connect."""
        self.server = await self.loop.create_server(
            lambda: ConnectionProtocol(
                self.name,
                self.client_connected,
                self.client_disconnected,
                self.data_received,
            ),
            self.host,
            self.port,
            family=AF_INET,
        )
        _LOGGER.info(
            "Listening for %s connection on %s port %s", self.name, self.host, self.port
        )

    def client_connected(self, transport: asyncio.Transport):
        """Connected callback."""

        # Add client to clients tracker
        client_id = self.get_client_id(transport)
        self.clients[client_id] = ClientConnection(transport, dt.datetime.now())

        _LOGGER.info(
            "Client connected to %s %s server. Clients: %s",
            self.name,
            client_id,
            len(self.clients),
        )
        _LOGGER.debug("Connections: %s", self.clients)

        if self.cb_connected:
            self.cb_connected(self.name, client_id)

        # If needs keepalive timer, start it
        if self.cb_keep_alive and not self.keep_alive_timer_task:
            self.keep_alive_timer_task = self.loop.create_task(
                self.keep_alive_timer(), name="Keep-alive timer"
            )
            _LOGGER.info("Started Keep-alive Timer")

    def data_received(self, transport: asyncio.Transport, data: bytes):
        """Callback for when data received."""

        client_id = self.get_client_id(transport)

        # Update client last received
        self.clients[client_id].last_received_message = dt.datetime.now()

        # Send message to coordinator callback
        if self.cb_received:
            self.cb_received(self.name, client_id, data)

    def send_message(self, client_id: str, data: bytes) -> bool:
        """Send data over transport."""
        if self.clients:
            # Check there are connected clients
            if client_id not in self.clients:
                client_id = list(self.clients.keys())[0]

            transport = self.get_transport(client_id)

            if transport:
                transport.write(data)
                _LOGGER.debug("Sent message via %s connection\n", client_id)

                # Update client last sent
                self.clients[client_id].last_sent_message = dt.datetime.now()

                return True
        _LOGGER.error(
            "Cannot send message to %s %s.  Not connected\n", self.name, client_id
        )
        return False

    def client_disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        client_id = self.get_client_id(transport)
        _LOGGER.info(
            "Client disconnected from %s %s",
            self.name,
            client_id,
        )

        # Remove client id from list of clients
        try:
            del self.clients[client_id]
        except KeyError:
            _LOGGER.error(
                "Client does not exist trying to remove client form client list"
            )

        _LOGGER.debug("Clients remaining: %s. %s", len(self.clients), self.clients)

        # If has keepalive timer, stop it if no more clients
        if len(self.clients) == 0:
            if self.keep_alive_timer_task and not self.keep_alive_timer_task.done():
                _LOGGER.info(
                    "Stopping keepalive timer for %s due to no connections", self.name
                )
                self.keep_alive_timer_task.cancel()
                self.keep_alive_timer_task = None

        if self.cb_disconnected:
            self.cb_disconnected(self.name, client_id)

    def disconnect_client(self, client_id: str):
        """Disconnect client."""
        transport = self.get_transport(client_id)
        if transport:
            if transport.can_write_eof():
                transport.write_eof()
            transport.close()

    async def shutdown(self):
        """Disconect the server."""

        # Stop keep alive timer
        if self.keep_alive_timer_task and not self.keep_alive_timer_task.done():
            _LOGGER.info("Stopping keepalive timer for %s", self.name)
            self.keep_alive_timer_task.cancel()

        for client_id in self.clients:
            _LOGGER.info("Disconnecting from %s %s", self.name, client_id)
            self.disconnect_client(client_id)
        self.server.close()
        await self.server.wait_closed()

    async def keep_alive_timer(self):
        """Keep alive timer

        To be run in a task
        """

        while True:
            await asyncio.sleep(1)
            for client_id, client in self.clients.items():
                if (
                    client.last_received_message
                    and (
                        dt.datetime.now() - client.last_received_message
                    ).total_seconds()
                    > KEEPALIVE_TIMER
                ):
                    self.cb_keep_alive(self.name, client_id)
                    await asyncio.sleep(5)
