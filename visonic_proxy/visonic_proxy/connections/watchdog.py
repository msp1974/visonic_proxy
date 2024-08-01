"""Disconnects connections that have had no traffic for a period."""

import asyncio
from collections.abc import Callable
import contextlib
import datetime as dt
import logging

from ..const import ConnectionName
from ..events import Event, EventType, fire_event, subscribe
from ..helpers import log_message

_LOGGER = logging.getLogger(__name__)


class Watchdog:
    """Watchdog manager.

    Fires a disconnection event if last activity is longer than inactive period
    """

    def __init__(self, name: ConnectionName, inactive_period: int = 120):
        """Initialise."""
        self.name = name
        self.inactive_period: int = inactive_period
        self._run_watchdog: bool = True
        self._last_activity_tracker: dict[str, dt.datetime] = {}
        self._task: asyncio.Task = None
        self._watchdog_timer: asyncio.TimerHandle = None
        self._unsubscribe_listeners: list[Callable] = []

    def start(self):
        """Start watchdog timer."""
        # Subscribe to data received
        self._unsubscribe_listeners = [
            subscribe(self.name, EventType.CONNECTION, self.notify_activity),
            subscribe(self.name, EventType.DATA_RECEIVED, self.notify_activity),
            subscribe(self.name, EventType.DISCONNECTION, self.remove_client),
        ]

        self._schedule_next_run()
        _LOGGER.info("Started %s Watchdog Timer", self.name)

    def _schedule_next_run(self):
        """Schedule next run of watchdog."""
        loop = asyncio.get_running_loop()
        self._watchdog_timer = loop.call_later(15, self._runner)

    async def stop(self):
        """Stop watchdog timer."""
        self._run_watchdog = False

        # Unsubscribe all listeners
        for unsub in self._unsubscribe_listeners:
            unsub()

        if self._watchdog_timer and not self._watchdog_timer.cancelled():
            self._watchdog_timer.cancel()

        # if self._task and not self._task.done():
        #    self._task.cancel()
        #    while not self._task.done():
        #        await asyncio.sleep(0)

    async def notify_activity(self, event: Event):
        """Update last activity."""
        # _LOGGER.info("Client %s added to %s watchdog", event.client_id, self.name)
        self._last_activity_tracker[event.client_id] = dt.datetime.now()

    def remove_client(self, event: Event):
        """Remove client id from watchdog list."""
        # _LOGGER.info("Client %s removed from %s watchdog", event.client_id, self.name)
        if self._last_activity_tracker.get(event.client_id):
            del self._last_activity_tracker[event.client_id]

    def _runner(self):
        """Check for old connections and disconnect."""
        log_message("Running %s Watchdog", self.name, level=6)
        if self._last_activity_tracker:
            clients_to_disconnect = [
                client_id
                for client_id, last_activity in self._last_activity_tracker.items()
                if (
                    last_activity
                    and (dt.datetime.now() - last_activity).total_seconds()
                    > self.inactive_period
                )
            ]
            for client_id in clients_to_disconnect:
                _LOGGER.info(
                    "WATCHDOG -> Disconnecting %s %s due to inactivity",
                    self.name,
                    client_id,
                )
                fire_event(Event(self.name, EventType.REQUEST_DISCONNECT, client_id))
                with contextlib.suppress(KeyError):
                    del self._last_activity_tracker[client_id]

        # Reschedule
        if self._run_watchdog:
            self._schedule_next_run()

        log_message("Finished %s Watchdog run", self.name, level=6)
