"""Constants."""

from enum import IntEnum, StrEnum
import logging

PROXY_MODE = True
LOG_LEVEL = logging.INFO
LOG_TO_FILE = False
LOG_FILES_TO_KEEP = 10

# TODO: UPDATE THESE!
# Level of messagestobe logged.
# 1 just messages and errors/warnings
# 2 same as 1 plus forward info
# 3 same as 2 plus keepalives (if in non Proxy mode - in Proxy mode, same as 2)
# 4 same as 3 plus acks
# 5 same as 4 plus web messages
# 6 same as 5 plus full PL31 raw message and not forwarded messages
MESSAGE_LOG_LEVEL = 5


VISONIC_HOST = "52.58.105.181"
MESSAGE_PORT = 5001
ALARM_MONITOR_PORT = 5002
VISONIC_MONITOR_PORT = 5003
KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
ACK_TIMEOUT = 5  # How long to wait for ACK before continuing
TEXT_UNKNOWN = "UNKNOWN"

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
NAK = "NAK"

MONITOR_SERVER_DOES_ACKS = False
STATUS_COMMAND = "e0"
ACTION_COMMAND = "e1"

DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"


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

    CM = "Connection_Manager"
    ALARM = "Alarm"
    VISONIC = "Visonic"
    ALARM_MONITOR = "Alarm_Monitor"
    VISONIC_MONITOR = "Visonic_Monitor"


class ConnectionSourcePriority(IntEnum):
    """Message priority for source."""

    CM = 0
    ALARM = 1
    VISONIC = 2
    ALARM_MONITOR = 3
