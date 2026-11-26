"""Handles system event bus."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
import inspect
import logging
import traceback

from visonic_proxy.const import LOGGER_NAME, ConnectionName

ALL_CLIENTS = "all"

_LOGGER = logging.getLogger(LOGGER_NAME)


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
    SUBSCRIBED_MESSAGE = "subscribed_message"
    NEW_CAMERA_IMAGE = "camera_image"


@dataclass
class Event:
    """Class to hold event."""

    name: ConnectionName
    event_type: EventType | str
    client_id: int | str | None = None
    event_data: str | dict | object | None = None
    destination: ConnectionName | str | None = None
    destination_client_id: int | str | None = None


class Events:
    """Class to manage events."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        """Initialise."""
        self._loop = loop
        self.listeners: dict[str, list[Callable]] = {}
        self._background_tasks: set[asyncio.Task] = set()

    def subscribe(
        self, name: str, event_type: EventType | str, callback: Callable
    ) -> Callable:
        """Subscribe to events.

        Returns function to unsubscribe
        """
        event_id = f"{name}__{event_type}"
        if event_id in self.listeners:
            self.listeners[event_id].append(callback)
        else:
            self.listeners[event_id] = [callback]
        return partial(self._unsubscribe, event_id, callback)

    def _unsubscribe(self, event_id: str, callback: Callable):
        """Unsubscribe to events."""
        if event_id in self.listeners:
            remaining = [cb for cb in self.listeners[event_id] if cb != callback]
            if remaining:
                self.listeners[event_id] = remaining
            else:
                del self.listeners[event_id]

    def fire_event_later(self, delay: float, event: Event) -> asyncio.TimerHandle:
        """Fire event after specified time delay in seconds."""
        return self._loop.call_later(delay, self.fire_event, event)

    async def _async_fire_event(self, event: Event) -> bool:
        """Notify event to all listeners without letting one failure block others."""
        event_ids = [f"all__{event.event_type}", f"{event.name}__{event.event_type}"]
        had_error = False

        for event_id in event_ids:
            callbacks = list(self.listeners.get(event_id, ()))
            for callback in callbacks:
                try:
                    _LOGGER.debug("Firing Event: %s - %s", event_id, callback)
                    _LOGGER.debug("Event: %s", event)
                    if inspect.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as ex:  # noqa: BLE001
                    had_error = True
                    _LOGGER.error("Error dispatching event %s: %s", event_id, ex)
                    _LOGGER.error(traceback.format_exc())
        return not had_error

    def fire_event(self, event: Event) -> bool:
        """Notify event to all listeners."""
        task = self._loop.create_task(
            self._async_fire_event(event), name=f"Fire Event - {event.event_type}"
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return True

    async def async_fire_event(self, event: Event):
        """Notify event to all listeners."""
        await self._async_fire_event(event)
