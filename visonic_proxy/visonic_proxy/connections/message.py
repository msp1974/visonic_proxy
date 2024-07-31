"""Message."""

from dataclasses import dataclass

from ..builder import NonPowerLink31Message
from ..const import ConnectionName
from ..decoders.pl31_decoder import PowerLink31Message


@dataclass
class QueuedMessage:
    """Queued message."""

    q_id: int
    source: ConnectionName
    source_client_id: str
    destination: ConnectionName
    destination_client_id: str
    message: PowerLink31Message | NonPowerLink31Message
    requires_ack: bool

    def __gt__(self, other):
        """Greater than."""
        return self.q_id > other.q_id

    def __lt__(self, other):
        """Less than."""
        return self.q_id < other.q_id
