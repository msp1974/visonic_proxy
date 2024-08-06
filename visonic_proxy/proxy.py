"""Proxy Data Object.

This is passed to all classes
"""

from dataclasses import dataclass
import datetime as dt
import logging
from typing import Any

from visonic_proxy.helpers import log_message

from .enums import ConnectionName, ConnectionPriority, ConnectionStatus
from .events import Events


@dataclass
class ConnectionInfo:
    """Class to hold connection."""

    name: ConnectionName
    id: int
    connection: Any
    status: ConnectionStatus
    connection_priority: int = 1
    requires_ack: bool = True
    send_non_pl31_messages: bool = False
    last_received: dt.datetime = None
    last_sent: dt.datetime = None


class Proxy:
    """Proxy object."""

    def __init__(self):
        """Initialise."""

        self.panel_id: str = None
        self.account_id: str = None

        self.clients = Clients()
        self.events = Events()
        self.message_tracker = {}  # TODO: Add message id and last timestamtp here
        self.status = SystemStatus()

        self.last_message_no: int = 0
        self.last_message_timestamp: dt = dt.datetime.now()

    def get_next_message_id(self) -> int:
        """Increment message id and return it."""
        self.last_message_no = self.last_message_no + 1
        return self.last_message_no


@dataclass
class SystemStatus:
    """Holds system status."""

    disconnected_mode: bool = True
    download_mode: bool = False
    proxy_mode: bool = False
    stealth_mode: bool = False


class Clients:
    """Class to hold client connection info."""

    def __init__(self):
        """Initialise."""
        self._clients: dict[str, dict[int, ConnectionInfo]] = {}

    def add(
        self,
        name: ConnectionName,
        client_id: int,
        connection: Any,
        connection_status: ConnectionStatus,
        connection_priority: ConnectionPriority = 1,
        requires_ack: bool = True,
        send_non_pl31_messages: bool = False,
    ):
        """Add client to list of connected clients."""
        if name not in self._clients:
            # No exising client of name registered - create entry
            self._clients[name] = {}
        elif (
            client_id in self._clients[name]
            and self._clients[name][client_id].status == ConnectionStatus.CONNECTED
        ):
            log_message(
                "%s client with id %s is already registered",
                level=0,
                log_level=logging.ERROR,
            )
            return

        # Now add/update our client record
        self._clients[name][client_id] = ConnectionInfo(
            name=name,
            id=client_id,
            connection=connection,
            status=connection_status,
            connection_priority=connection_priority,
            requires_ack=requires_ack,
            send_non_pl31_messages=send_non_pl31_messages,
        )
        log_message(
            "%s %s registered with connection manager as %s",
            name,
            client_id,
            connection_status.name,
            level=5,
        )

    def remove(self, name: ConnectionName, client_id: int):
        """Remove a client from connected clients."""
        try:
            del self._clients[name][client_id]
        except KeyError:
            pass
        finally:
            log_message(
                "%s %s removed from connection manager", name, client_id, level=6
            )

    def get_connection_priroity(self, name: ConnectionName, client_id: int) -> int:
        """Get priority of conection."""
        if client := self.get_client(name, client_id):
            return client.connection_priority
        # If not a client ie Command Manager, retrun Cm priority
        return ConnectionPriority.CM

    def get_client(self, name: ConnectionName, client_id: int) -> ConnectionInfo | None:
        """Get connection info for connected client."""
        if client_id == 0:
            # This will come from CM or Command manager and is wanting the first client connection
            return self.get_first_client(name)
        try:
            return self._clients[name][client_id]
        except KeyError:
            return None

    def get_clients(self, name: ConnectionName) -> list[ConnectionInfo] | None:
        """Get connection info for connected clients by connection name."""
        try:
            return list(self._clients[name].values())
        except KeyError:
            return []

    def get_first_client(self, name: ConnectionName) -> ConnectionInfo | None:
        """Get connection info for first client in connection."""
        try:
            if client_ids := list(self._clients[name].keys()):
                first_client = min(client_ids)
                return self._clients[name][first_client]
        except KeyError:
            return None

    @property
    def connections(self) -> list[str]:
        """Get connection names of registered clients."""
        return self._clients.keys()

    def count(self, name: ConnectionName) -> int:
        """Return count of clients by connection name."""
        try:
            return len(list(self._clients[name]))
        except KeyError:
            return 0

    def update(
        self, name: ConnectionName, client_id: int, connection_info: ConnectionInfo
    ):
        """Update connection info record for client."""
        try:
            if self._clients[name][client_id]:
                self._clients[name][client_id] = connection_info
        except KeyError:
            log_message(
                "Error updating client connection info.  CLient does not exist.",
                level=0,
                log_level=logging.ERROR,
            )

    def update_status(
        self, name: ConnectionName, client_id: int, status: ConnectionStatus
    ):
        """Update connection status of client."""
        try:
            self._clients[name][client_id].status = status
        except KeyError:
            log_message(
                "Error updating client status.  No existing client entry.",
                level=0,
                log_level=logging.ERROR,
            )
