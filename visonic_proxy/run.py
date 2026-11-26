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
    ConnectionName,
    ManagerStatus,
    MsgLogLevel,
)
from visonic_proxy.helpers.env import (
    is_running_as_addon,
    process_env_vars,
    redact_config_value,
)
from visonic_proxy.helpers.ssl import validate_ssl_certificates
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

        # Process config from add-on options / env before configuring logger
        config = process_env_vars()

        # Initiate logger using resolved config
        log_class = VPLogger(
            log_file=config.LOG_FILE,
            log_level=config.LOG_LEVEL,
            message_log_level=int(config.MESSAGE_LOG_LEVEL),
        )

        # Start a new log on each restart when file logging is enabled
        if config.LOG_FILE:
            log_class.rollover()

        _LOGGER.info("Version: %s", __VERSION__)
        _LOGGER.info(
            "Environment: %s", "HA Addon" if is_running_as_addon() else "Standalone"
        )

        self.proxy = Proxy(self.loop, log_class, config)
        self.proxy.is_addon = is_running_as_addon()

        self.proxy.status.proxy_mode = self.proxy.config.PROXY_MODE

        _LOGGER.info("Proxy Mode: %s", self.proxy.config.PROXY_MODE)
        _LOGGER.info("Websocket Mode: %s", self.proxy.config.WEBSOCKET_MODE)
        _LOGGER.info("Log Level: %s", logging.getLevelName(self.proxy.config.LOG_LEVEL))
        _LOGGER.info("Message Log Level: %s", self.proxy.config.MESSAGE_LOG_LEVEL)

        if (
            self.proxy.config.WEBSOCKET_MODE
            and not self.proxy.config.WEBSOCKET_AUTH_KEY
        ):
            _LOGGER.warning(
                "Websocket server running without WEBSOCKET_AUTH_KEY; "
                "configure an authentication key to protect alarm access."
            )

        # Output config to debug (with sensitive keys redacted)
        if self.proxy.config.LOG_LEVEL == logging.DEBUG:
            _LOGGER.debug("%s  FULL CONFIG  %s", "".rjust(20, "-"), "".rjust(20, "-"))
            configs = [
                (attr, getattr(self.proxy.config, attr))
                for attr in dir(self.proxy.config)
                if not callable(getattr(self.proxy.config, attr))
                and not attr.startswith("__")
            ]
            for key, val in configs:
                _LOGGER.debug("%s: %s", key, redact_config_value(key, val))
            _LOGGER.debug("%s", "".rjust(60, "-"))

        # Validate/generate SSL certificates
        certs_full_path = f"{os.path.dirname(os.path.realpath(__file__))}/{self.proxy.config.SSL_CERT_PATH}"
        validate_ssl_certificates(certs_full_path)

        # Start connection servers
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
