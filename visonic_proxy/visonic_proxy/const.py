"""Constants."""

from enum import IntEnum, StrEnum
import logging

PROXY_MODE = True
LOG_LEVEL = logging.INFO
LOG_TO_FILE = False
LOG_FILES_TO_KEEP = 10

# Level of messagestobe logged.
# 1 just decoded messages
# 2 same as 1 plus raw message
# 3 same as 2 plus decoder info
# 4 same as 3 plus structured message, paged messages
# 5 same as 4 plus powerlink message decoded, ACKs, forwarding info, keep-alives
MESSAGE_LOG_LEVEL = 3


VISONIC_HOST = "52.58.105.181"
MESSAGE_PORT = 5001
ALARM_MONITOR_PORT = 5002
VISONIC_MONITOR_PORT = 5003
KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.

TEXT_UNKNOWN = "UNKNOWN"

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"


class Commands(StrEnum):
    """Available injector commands."""

    SHUTDOWN = "shutdown"
    SHOW = "show"


class MessagePriority(IntEnum):
    """Message priority enum."""

    IMMEDIATE = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class ConnectionName(StrEnum):
    """Connection name enum."""

    ALARM = "Alarm"
    VISONIC = "Visonic"
    ALARM_MONITOR = "Alarm_Monitor"
    VISONIC_MONITOR = "Visonic_Monitor"
