"""Track message numbers."""

import datetime as dt


class MessageTracker:
    """Tracker for messages."""

    last_message_no: int = 0
    last_message_timestamp: dt.datetime = 0

    @staticmethod
    def get_next():
        """Get next msg id."""
        return MessageTracker.last_message_no + 1

    @staticmethod
    def get_current():
        """Get current/last message id."""
        return MessageTracker.last_message_no
