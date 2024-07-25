"""Client connection class."""

import asyncio
import datetime as dt
from collections.abc import Callable
import logging
from socket import AF_INET

from .protocol import ConnectionProtocol

_LOGGER = logging.getLogger(__name__)


class ClientConnection:
    """Handles connection to visonic."""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        parent_connection_id: str,
        received_message_callback: Callable,
        connected_callback: Callable = None,
        disconnected_callback: Callable = None,
        run_watchdog: bool = False,
    ):
        """Init."""
        self.loop = asyncio.get_running_loop()
        self.name = name
        self.host = host
        self.port = port
        self.parent_connection_id = parent_connection_id
        self.cb_received = received_message_callback
        self.cb_connected = connected_callback
        self.cb_disconnected = disconnected_callback
        self.run_watchdog = run_watchdog

        self.last_received_message: dt.datetime = dt.datetime.now()
        self.last_sent_message: dt.datetime = None

        self.protocol = None
        self.transport: asyncio.Transport = None
        self.connected: bool = False

    async def connect(self):
        """Initiate connection to host."""

        _LOGGER.info(
            "Initiating connection to %s on behalf of %s",
            self.name,
            self.parent_connection_id,
        )

        self.transport, self.protocol = await self.loop.create_connection(
            lambda: ConnectionProtocol(
                self.name,
                self.connection_made,
                self.disconnected,
                self.data_received,
            ),
            self.host,
            self.port,
            family=AF_INET,
        )

    def connection_made(self, transport: asyncio.Transport):
        """Connected callback."""
        _LOGGER.info(
            "Connected to %s server on port %s for %s",
            self.name,
            self.port,
            self.parent_connection_id,
        )

        # Get ref to transport for writing
        self.transport = transport
        self.connected = True

        if self.cb_connected:
            self.cb_connected(self.name, self.parent_connection_id)

    def data_received(self, _: asyncio.Transport, data: bytes):
        """Callback for when data received."""

        self.last_received_message = dt.datetime.now()

        # Send message to coordinator callback
        if self.cb_received:
            self.cb_received(self.name, self.parent_connection_id, data)

    def send_message(self, client_id: str, data: bytes) -> bool:
        """Send data over transport."""
        if self.connected:
            try:
                self.transport.write(data)
                self.last_sent_message = dt.datetime.now()
                _LOGGER.debug(
                    "Sent message via %s %s connection\n", self.name, client_id
                )
                return True
            except Exception as ex:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "Exception occured sending message to %s - %s. %s",
                    self.name,
                    self.parent_connection_id,
                    ex,
                )
        _LOGGER.error("Cannot send message to %s.  Not connected\n", self.name)
        return False

    def disconnected(self, transport: asyncio.Transport):
        """Disconnected callback."""
        self.connected = False
        _LOGGER.info(
            "%s %s server has disconnected", self.name, self.parent_connection_id
        )
        if transport:
            transport.close()
        if self.cb_disconnected:
            self.cb_disconnected(self.name, self.parent_connection_id)

    async def shutdown(self):
        """Disconnect from Server."""
        _LOGGER.info(
            "Shutting down connection to %s for %s",
            self.name,
            self.parent_connection_id,
        )
        self.connected = False
        if self.transport:
            if self.transport.can_write_eof():
                self.transport.write_eof()
            self.transport.close()
