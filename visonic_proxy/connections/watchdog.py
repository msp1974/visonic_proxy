"""Disconnects connections that have had no traffic for a period."""

import asyncio
from collections.abc import Callable
import contextlib
import datetime as dt
import logging

from ..const import LOGGER_NAME, ConnectionName, MsgLogLevel
from ..events import Event, EventType
from ..proxy import Proxy

_LOGGER = logging.getLogger(LOGGER_NAME)


class Watchdog:
    """Watchdog manager.

    Fires a disconnection event if last activity is longer than inactive period
    """

    def __init__(self, proxy: Proxy, name: ConnectionName, inactive_period: int):
        """Initialise."""
        self.proxy = proxy
        self.name = name
        self.inactive_period = inactive_period
        self._run_watchdog: bool = True
        self._last_activity_tracker: dict[str, dt.datetime] = {}
        self._task: asyncio.Task = None
        self._watchdog_timer: asyncio.TimerHandle = None
        self._unsubscribe_listeners: list[Callable] = []

    def start(self):
        """Start watchdog timer."""
        # Subscribe to data received
        self._unsubscribe_listeners = [
            self.proxy.events.subscribe(
                self.name, EventType.CONNECTION, self.notify_activity
            ),
            self.proxy.events.subscribe(
                self.name, EventType.DATA_RECEIVED, self.notify_activity
            ),
            self.proxy.events.subscribe(
                self.name, EventType.DISCONNECTION, self.remove_client
            ),
        ]

        self._schedule_next_run()
        _LOGGER.info("Started %s Connection Watchdog", self.name, extra=MsgLogLevel.L5)

    def _schedule_next_run(self):
        """Schedule next run of watchdog."""
        self._watchdog_timer = self.proxy.loop.call_later(15, self._runner)

    async def stop(self):
        """Stop watchdog timer."""
        self._run_watchdog = False

        # Unsubscribe all listeners
        for unsub in self._unsubscribe_listeners:
            unsub()

        if self._watchdog_timer and not self._watchdog_timer.cancelled():
            self._watchdog_timer.cancel()

    async def notify_activity(self, event: Event):
        """Update last activity."""
        self._last_activity_tracker[event.client_id] = dt.datetime.now()

    def remove_client(self, event: Event):
        """Remove client id from watchdog list."""
        if self._last_activity_tracker.get(event.client_id):
            del self._last_activity_tracker[event.client_id]

    def _runner(self):
        """Check for old connections and disconnect."""
        _LOGGER.debug("Running %s Watchdog", self.name)
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
                    extra=MsgLogLevel.L1,
                )
                self.proxy.events.fire_event(
                    Event(self.name, EventType.REQUEST_DISCONNECT, client_id)
                )
                with contextlib.suppress(KeyError):
                    del self._last_activity_tracker[client_id]

        # Reschedule
        if self._run_watchdog:
            self._schedule_next_run()

        _LOGGER.debug("Finished %s Watchdog run", self.name)
