"""Initiates MITM server."""

import asyncio
import logging

from .connections.manager import ConnectionManager
from .const import Config, ConnectionName, ManagerStatus, MsgLogLevel
from .managers.message_router import MessageCoordinatorStatus
from .proxy import Proxy

_LOGGER = logging.getLogger(__name__)


class VisonicProxy:
    """Runner manager."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        """Initialise."""
        self.loop = loop
        self.connection_manager = None
        self.proxy = Proxy(self.loop)
        self.status: ManagerStatus
        self._task: asyncio.Task

    async def start(self):
        """Run managers."""
        self.proxy.status.proxy_mode = self.proxy.config.PROXY_MODE
        _LOGGER.info("Proxy Mode: %s", self.proxy.config.PROXY_MODE)
        _LOGGER.info("Websocket Mode: %s", self.proxy.config.WEBSOCKET_MODE)
        _LOGGER.info("Log Level: %s", logging.getLevelName(Config.LOG_LEVEL))
        _LOGGER.info("Message Log Level: %s", Config.MESSAGE_LOG_LEVEL)

        # Output config to debug
        if Config.LOG_LEVEL == logging.DEBUG:
            _LOGGER.debug("%s  CONFIG  %s", "".rjust(20, "-"), "".rjust(20, "-"))
            configs = [
                (attr, getattr(self.proxy.config, attr))
                for attr in vars(self.proxy.config)
                if not callable(getattr(self.proxy.config, attr))
                and not attr.startswith("__")
            ]
            for config in configs:
                _LOGGER.debug("%s: %s", config[0], config[1])
            _LOGGER.debug("%s", "".rjust(60, "-"))

        self.connection_manager = ConnectionManager(self.proxy)

        self.status = ManagerStatus.STARTING
        _LOGGER.info("Proxy Server is starting")

        await self.connection_manager.start()

        if self.connection_manager.status == ManagerStatus.RUNNING:
            _LOGGER.info("Proxy Server is running")

        while self.connection_manager.status != MessageCoordinatorStatus.STOPPED:
            await asyncio.sleep(10)
            _LOGGER.debug("TASKS: %s", [t.get_name() for t in asyncio.all_tasks()])

            _LOGGER.info(
                "-------------------------------------------------------------------------------------------",
                extra=MsgLogLevel.L2,
            )
            _LOGGER.info(
                "CONNECTIONS: Alarm: %s, Visonic: %s, HA: %s",
                self.proxy.clients.count(ConnectionName.ALARM),
                self.proxy.clients.count(ConnectionName.VISONIC),
                self.proxy.clients.count(ConnectionName.ALARM_MONITOR),
                extra=MsgLogLevel.L2,
            )
            _LOGGER.info(
                "MODES: Disconnected Mode: %s, Stealth Mode: %s, Download Mode: %s",
                self.proxy.status.disconnected_mode,
                self.proxy.status.stealth_mode,
                self.proxy.status.download_mode,
                extra=MsgLogLevel.L2,
            )
            _LOGGER.info(
                "Queue Size: Receive: %s, Send: %s",
                self.connection_manager.flow_manager.receive_queue.qsize(),
                self.connection_manager.flow_manager.sender_queue.qsize(),
                extra=MsgLogLevel.L2,
            )
            _LOGGER.info(
                "-------------------------------------------------------------------------------------------",
                extra=MsgLogLevel.L2,
            )

    async def stop(self):
        """Stop."""
        await self.connection_manager.stop()
        _LOGGER.info("Proxy Server is stopped")
