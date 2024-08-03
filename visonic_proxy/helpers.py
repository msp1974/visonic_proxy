"""Helper functions."""

import logging

from .const import MESSAGE_LOG_LEVEL, ConnectionName

_LOGGER = logging.getLogger(__name__)


def log_message(message: str, *args, level: int = 5):
    """Log message to logger if level."""
    if level <= MESSAGE_LOG_LEVEL:
        _LOGGER.info(message, *args)


def get_connection_id(name: ConnectionName, client_id: str) -> str:
    """Return connection id."""
    return f"{name}_{client_id}"
