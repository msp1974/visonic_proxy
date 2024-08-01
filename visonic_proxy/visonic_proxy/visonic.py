"""Initiates MITM server."""

import asyncio
import logging

from .helpers import log_message
from .router import MessageCoordinatorStatus, MessageRouter

_LOGGER = logging.getLogger(__name__)


class Runner:
    """Runner manager."""

    def __init__(self, evloop):
        """Initialise."""
        self.loop = evloop
        self.mm: MessageRouter = None

    async def run(self):
        """Run servers."""
        self.mm = MessageRouter()
        await self.mm.start()

        # Give it time to start
        await asyncio.sleep(5)

        while self.mm.status != MessageCoordinatorStatus.STOPPED:
            await asyncio.sleep(10)
            log_message(
                "TASKS: %s", [t.get_name() for t in asyncio.all_tasks()], level=6
            )

            cc = self.mm._connection_coordinator  # noqa: SLF001
            alarm_clients = list(cc.alarm_server.clients)
            visonic_clients = list(cc.visonic_clients)
            monitor_clients = list(cc.monitor_server.clients)
            log_message(
                "-------------------------------------------------------------------------------------------",
                level=2,
            )
            log_message(
                "CONNECTIONS: Alarm: %s, Visonic: %s, HA: %s",
                alarm_clients,
                visonic_clients,
                monitor_clients,
                level=2,
            )
            log_message(
                "MODES: Disconnected Mode: %s, Stealth Mode: %s",
                cc.is_disconnected_mode,
                cc.stealth_mode,
                level=2,
            )
            log_message(
                "-------------------------------------------------------------------------------------------",
                level=2,
            )

            """
            alarm_q = cc.alarm_server.sender_queue.qsize()
            visonic_q = [
                client.sender_queue.qsize() for _, client in cc.visonic_clients.items()
            ]
            monitor_q = cc.monitor_server.sender_queue.qsize()
            log_message(
                "SENDER Q'S: Alarm: %s, Visonic: %s, Monitor: %s",
                alarm_q,
                visonic_q,
                monitor_q,
                level=6,
            )

            log_message(
                "RTS: Alarm %s, Visonic %s, Monitor %s",
                cc.alarm_server.is_rts,
                [client.is_rts for _, client in cc.visonic_clients.items()],
                cc.monitor_server.is_rts,
                level=6,
            )
            """

    async def stop(self):
        """Stop."""
        await self.mm.stop()
