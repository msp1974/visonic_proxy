"""Handles system event bus."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
import inspect
import logging
import traceback
from typing import Callable

from visonic_proxy.enums import ConnectionName

ALL_CLIENTS = "all"

_LOGGER = logging.getLogger(__name__)


class EventType(StrEnum):
    """Event type enum."""

    CONNECTION = "connection"
    DISCONNECTION = "disconnection"
    REQUEST_CONNECT = "request_connect"
    REQUEST_DISCONNECT = "request_disconnect"
    WEB_REQUEST_CONNECT = "web_request_connect"
    DATA_RECEIVED = "data_received"
    DATA_SENT = "data_sent"
    SEND_KEEPALIVE = "keepalive"
    ACK_TIMEOUT = "ack_timeout"
    SET_MODE = "set_mode"


@dataclass
class Event:
    """Class to hold event."""

    name: ConnectionName
    event_type: int
    client_id: str | None = None
    event_data: str | dict | None = None
    destination: str = None
    destination_client_id: str = None


class Events:
    """Class to manage events."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        """Initialise."""
        self._loop = loop
        self.listeners: dict[str, list[Callable]] = {}

    def subscribe(
        self, name: str, event_type: EventType, callback: Callable
    ) -> Callable:
        """Subscribe to events.

        Returns function to unsubscribe
        """
        event_id = f"{name}__{event_type}"
        if event_id in self.listeners:
            self.listeners[event_id].append(callback)
        else:
            self.listeners[event_id] = [callback]
        # log_message("LISTENERS: %s", self.listeners, level=2)
        return partial(self._unsubscribe, event_id, callback)

    def _unsubscribe(self, event_id: str, callback: Callable):
        """Unsubscribe to events."""
        if event_id in self.listeners:
            for idx, cb in enumerate(self.listeners[event_id]):
                if cb == callback:
                    self.listeners[event_id].pop(idx)

            # Remove key if not more targets
            if len(self.listeners[event_id]) == 0:
                del self.listeners[event_id]

    def fire_event_later(self, delay: int, event: Event) -> asyncio.TimerHandle:
        """Fire event after specified time delay in seconds."""
        return self._loop.call_later(delay, self.fire_event, event)

    async def _async_fire_event(self, event: Event):
        """Notify event to all listeners."""
        event_ids = [f"all__{event.event_type}", f"{event.name}__{event.event_type}"]

        for event_id in event_ids:
            if event_id in self.listeners:
                try:
                    for callback in self.listeners[event_id]:
                        _LOGGER.debug("Firing Event: %s - %s", event_id, callback)
                        _LOGGER.debug("Event: %s", event)
                        if inspect.iscoroutinefunction(callback):
                            await callback(event)
                            await asyncio.gather()
                        else:
                            callback(event)
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.error("Error dispatching event.  Error is %s", ex)
                    _LOGGER.error(traceback.format_exc())
                    return False
        return True

    def fire_event(self, event: Event):
        """Notify event to all listeners."""
        self._loop.create_task(  # noqa: RUF006
            self._async_fire_event(event), name=f"Fire Event - {event.event_type}"
        )
        return True
