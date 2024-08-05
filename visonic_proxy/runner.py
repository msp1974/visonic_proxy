"""Initiates MITM server."""

import asyncio
import logging

from .connections.manager import ConnectionManager
from .enums import ConnectionName, ManagerStatus
from .helpers import log_message
from .message_router import MessageCoordinatorStatus
from .proxy import Proxy

_LOGGER = logging.getLogger(__name__)


class VisonicProxy:
    """Runner manager."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        """Initialise."""
        self.loop = loop
        self.connection_manager = None
        self.proxy = Proxy()
        self.status: ManagerStatus
        self._task: asyncio.Task

    async def start(self):
        """Run managers."""

        self.connection_manager = ConnectionManager(self.proxy)

        self.status = ManagerStatus.STARTING
        log_message("Proxy Server is starting", level=0)

        await self.connection_manager.start()

        if self.connection_manager.status == ManagerStatus.RUNNING:
            log_message("Proxy Server running", level=0)

        while self.connection_manager.status != MessageCoordinatorStatus.STOPPED:
            await asyncio.sleep(10)
            log_message(
                "TASKS: %s", [t.get_name() for t in asyncio.all_tasks()], level=6
            )

            log_message(
                "-------------------------------------------------------------------------------------------",
                level=2,
            )
            log_message(
                "CONNECTIONS: Alarm: %s, Visonic: %s, HA: %s",
                self.proxy.clients.count(ConnectionName.ALARM),
                self.proxy.clients.count(ConnectionName.VISONIC),
                self.proxy.clients.count(ConnectionName.ALARM_MONITOR),
                level=2,
            )
            log_message(
                "MODES: Disconnected Mode: %s, Stealth Mode: %s",
                self.proxy.status.disconnected_mode,
                self.proxy.status.stealth_mode,
                level=2,
            )
            log_message(
                "Queue Size: Receive: %s, Send: %s",
                self.connection_manager.flow_manager.receive_queue.qsize(),
                self.connection_manager.flow_manager.sender_queue.qsize(),
                level=2,
            )
            # log_message("Event Listeners: %s", self.proxy.events.listeners, level=2)
            log_message(
                "-------------------------------------------------------------------------------------------",
                level=2,
            )

    async def stop(self):
        """Stop."""
        await self.connection_manager.stop()
        log_message("Proxy Server is stopped", level=0)