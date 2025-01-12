#!/usr/bin/env python

"""Run Visonic Proxy."""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

# ruff: noqa: E402
import asyncio
import logging

from visonic_proxy import __VERSION__
from visonic_proxy.connections.manager import ConnectionManager
from visonic_proxy.const import (
    LOGGER_NAME,
    Config,
    ConnectionName,
    ManagerStatus,
    MsgLogLevel,
)
from visonic_proxy.helpers.env import get_env_var, is_running_as_addon, process_env_vars
from visonic_proxy.logger import VPLogger
from visonic_proxy.managers.message_router import MessageCoordinatorStatus
from visonic_proxy.proxy import Proxy

_LOGGER = logging.getLogger(LOGGER_NAME)


class VisonicProxy:
    """Runner manager."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
    ):
        """Initialise."""
        self.loop = loop
        self.logger: logging.Logger = None
        self.proxy: Proxy = None
        self.status: ManagerStatus
        self._task: asyncio.Task

    async def start(self):
        """Run managers."""

        # Initiate logger
        log_class = VPLogger()

        # start a new log on each restart
        if Config.LOG_FILE or get_env_var("log_file"):
            log_class.rollover()

        _LOGGER.info("Version: %s", __VERSION__)
        _LOGGER.info(
            "Environment: %s", "HA Addon" if is_running_as_addon() else "Standalone"
        )

        # Process config env and set config
        _LOGGER.debug("Processing ENV variables...")
        config = process_env_vars(log_class)

        # Set message log level in case changed by env value
        log_class.message_filter.set_message_log_level(int(config.MESSAGE_LOG_LEVEL))

        self.proxy = Proxy(self.loop, config)
        self.proxy.is_addon = is_running_as_addon()

        self.proxy.status.proxy_mode = self.proxy.config.PROXY_MODE

        _LOGGER.info("Proxy Mode: %s", self.proxy.config.PROXY_MODE)
        _LOGGER.info("Websocket Mode: %s", self.proxy.config.WEBSOCKET_MODE)
        _LOGGER.info("Log Level: %s", logging.getLevelName(self.proxy.config.LOG_LEVEL))
        _LOGGER.info("Message Log Level: %s", self.proxy.config.MESSAGE_LOG_LEVEL)

        # Output config to debug
        if self.proxy.config.LOG_LEVEL == logging.DEBUG:
            _LOGGER.debug("%s  FULL CONFIG  %s", "".rjust(20, "-"), "".rjust(20, "-"))
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


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    vp = VisonicProxy(loop)
    task = loop.create_task(vp.start(), name="ProxyRunner")
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        _LOGGER.info("Keyboard interrupted. Exit.")
        task.cancel()
        loop.run_until_complete(vp.stop())
    loop.close()
