"""Initiates MITM server."""

import asyncio
import logging

from .connections.manager import ConnectionProfile, ConnectionType, Forwarder

from .const import ALARM_MONITOR_PORT,  MESSAGE_PORT, VISONIC_HOST, ConnectionName
from .manager import (
    MessageCoordinator,
    MessageCoordinatorStatus,
)

from .const import PROXY_MODE


_LOGGER = logging.getLogger(__name__)


class Runner:
    """Runner manager."""

    def __init__(self, evloop):
        self.loop = evloop
        self.mm: MessageCoordinator = None

        self.my_ip = "0.0.0.0"

    async def run(self):
        """Run servers."""
        if PROXY_MODE:
            connections = [
                ConnectionProfile(
                    name=ConnectionName.ALARM,
                    connection_type=ConnectionType.SERVER,
                    host=self.my_ip,
                    port=MESSAGE_PORT,
                    forwarders=[
                        Forwarder(destination=ConnectionName.VISONIC),
                        Forwarder(
                            destination=ConnectionName.ALARM_MONITOR,
                            forward_to_all_connections=True,
                            remove_pl31_wrapper=True,
                        ),
                    ],
                    run_watchdog=True,
                ),
                ConnectionProfile(
                    name=ConnectionName.VISONIC,
                    connection_type=ConnectionType.CLIENT,
                    host=VISONIC_HOST,
                    port=MESSAGE_PORT,
                    connect_with=ConnectionName.ALARM,
                    forwarders=[
                        Forwarder(destination=ConnectionName.ALARM),
                        # Add the below forwarder to get Visonic messages on Alarm Monitor connection
                        #Forwarder(
                        #    destination=ConnectionName.ALARM_MONITOR,
                        #    forward_to_all_connections=True,
                        #    remove_pl31_wrapper=True,
                        #)
                    ],
                    run_watchdog=True,
                ),
                ConnectionProfile(
                    name=ConnectionName.ALARM_MONITOR,
                    connection_type=ConnectionType.SERVER,
                    host=self.my_ip,
                    port=ALARM_MONITOR_PORT,
                    forwarders=[
                        Forwarder(destination=ConnectionName.ALARM),
                    ],
                    # Remove this to get all ACKs.  This only sends ACKs for messages sent by this connection
                    track_acks = True,
                    preprocess=True,
                ),
            ]
        else:
            connections = [
                ConnectionProfile(
                    name=ConnectionName.ALARM,
                    connection_type=ConnectionType.SERVER,
                    host=self.my_ip,
                    port=MESSAGE_PORT,
                    forwarders=[
                        Forwarder(
                            destination=ConnectionName.ALARM_MONITOR,
                            forward_to_all_connections=True,
                            remove_pl31_wrapper=True,
                        )
                    ],
                    send_keepalives=True,
                    ack_received_messages=True,
                    run_watchdog=True,
                ),
                ConnectionProfile(
                    name=ConnectionName.ALARM_MONITOR,
                    connection_type=ConnectionType.SERVER,
                    host=self.my_ip,
                    port=ALARM_MONITOR_PORT,
                    forwarders=[
                        Forwarder(
                            destination=ConnectionName.ALARM,
                        )
                    ],
                    preprocess=True,
                ),
            ]

        self.mm = MessageCoordinator(self.loop, connections)
        await self.mm.start()

        # Give it time to start
        await asyncio.sleep(5)

        while self.mm.status != MessageCoordinatorStatus.STOPPED:
            await asyncio.sleep(1)

    async def stop(self):
        """Stop"""
        await self.mm.stop()
