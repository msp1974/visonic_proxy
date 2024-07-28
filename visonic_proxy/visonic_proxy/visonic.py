"""Initiates MITM server."""

import asyncio
import logging

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
            await asyncio.sleep(1)

    async def stop(self):
        """Stop."""
        await self.mm.stop()
