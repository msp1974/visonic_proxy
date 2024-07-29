"""Helper functions."""

import logging

from .const import MESSAGE_LOG_LEVEL

_LOGGER = logging.getLogger(__name__)


def log_message(message: str, *args, level: int = 5):
    """Log message to logger if level."""
    if level <= MESSAGE_LOG_LEVEL:
        _LOGGER.info(message, *args)
