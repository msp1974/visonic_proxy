"""Protocol for connections."""

import asyncio
from collections.abc import Callable
import logging

_LOGGER = logging.getLogger(__name__)


class ConnectionProtocol(asyncio.Protocol):
    """Visonic Connection Protocol."""

    def __init__(
        self,
        name: str,
        cb_connection: Callable,
        cb_disconnection: Callable,
        cd_data_received: Callable,
    ):
        self.name = name
        self.cb_connection = cb_connection
        self.cb_disconnection = cb_disconnection
        self.cb_data_received = cd_data_received

        self.transport: asyncio.Transport = None

    def connection_made(self, transport):
        self.transport = transport
        if self.cb_connection:
            self.cb_connection(self.transport)

    def data_received(self, data):
        if self.cb_data_received:
            self.cb_data_received(self.transport, data)

    def connection_lost(self, exc):
        _LOGGER.debug("%s connection disconnected.  Exception is %s", self.name, exc)
        if self.cb_disconnection:
            self.cb_disconnection(self.transport)
