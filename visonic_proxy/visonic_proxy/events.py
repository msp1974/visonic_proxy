"""Handles system event bus."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
import inspect
from inspect import signature
import logging
import traceback

from .decoders.pl31_decoder import PowerLink31Message

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


@dataclass
class Event:
    """Class to hold event."""

    name: str
    event_type: int
    client_id: str | None = None
    event_data: str | int | bytes | PowerLink31Message | None = None


class EventSubscribers:
    """Class to hold subscribers."""

    listeners: dict[str, list[Callable]] = {}


_fire_later_tasks: list[asyncio.Task] = []


def subscribe(name: str, event_type: EventType, callback: Callable) -> Callable:
    """Subscribe to events.

    Returns function to unsubscribe
    """
    # Ensure any All requests are in lowercase
    if name.lower() == "all":
        name = name.lower()

    event_id = f"{name}|{event_type}"
    if event_id in EventSubscribers.listeners:
        # Multiple subscribers to this message class
        # Add callback to list
        EventSubscribers.listeners[event_id].append(callback)
    else:
        EventSubscribers.listeners[event_id] = [callback]

    return partial(_unsubscribe, event_id, callback)


def _unsubscribe(event_id: str, callback: Callable):
    """Unsubscribe to events."""
    if event_id in EventSubscribers.listeners:
        for idx, cb in enumerate(EventSubscribers.listeners[event_id]):
            if cb == callback:
                EventSubscribers.listeners[event_id].pop(idx)

    # Remove key if not more targets
    if not EventSubscribers.listeners[event_id]:
        del EventSubscribers.listeners[event_id]


async def async_fire_event_later(delay: int, event: Event) -> asyncio.TimerHandle:
    """Fire event after specified time delay in seconds."""
    loop = asyncio.get_running_loop()
    return loop.call_later(delay, fire_event, event)


async def async_fire_event(event: Event):
    """Notify event to all listeners."""

    event_ids = [f"all|{event.event_type}", f"{event.name}|{event.event_type}"]

    for event_id in event_ids:
        if event_id in EventSubscribers.listeners:
            try:
                for callback in EventSubscribers.listeners[event_id]:
                    # Verify it can be passed a message parameter
                    # _LOGGER.info("Firing: %s", event_id)
                    sig = signature(callable)
                    params = sig.parameters
                    if len(params) == 1:
                        if inspect.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                    elif inspect.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
            except Exception as ex:  # noqa: BLE001
                _LOGGER.error("Error dispatching event.  Error is %s", ex)
                _LOGGER.error(traceback.format_exc())
                return False
    return True


def fire_event(event: Event):
    """Notify event to all listeners."""
    # loop = asyncio.get_event_loop()
    asyncio.create_task(  # noqa: RUF006
        async_fire_event(event), name="Async dispatcher"
    )
    return True
