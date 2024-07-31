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
MESSAGE_LOG_LEVEL = 3


VISONIC_HOST = "52.58.105.181"
MESSAGE_PORT = 5001
ALARM_MONITOR_PORT = 5002
VISONIC_MONITOR_PORT = 5003
KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
ACK_TIMEOUT = 3  # How long to wait for ACK before continuing
TEXT_UNKNOWN = "UNKNOWN"

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
DUH = "DUH"
NAK = "NAK"

MONITOR_SERVER_DOES_ACKS = False
STATUS_COMMAND = "e0"
ACTION_COMMAND = "e1"

DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"


class ConnectionType(StrEnum):
    """Connection Type enum."""

    CLIENT = "client"
    SERVER = "server"


class ConnectionName(StrEnum):
    """Connection name enum."""

    CM = "Connection_Manager"
    ALARM = "Alarm"
    VISONIC = "Visonic"
    ALARM_MONITOR = "Alarm_Monitor"
    VISONIC_MONITOR = "Visonic_Monitor"


class ConnectionSourcePriority(IntEnum):
    """Message priority for source."""

    CM = 3
    ALARM = 1
    VISONIC = 2
    ALARM_MONITOR = 3


class ManagedMessages(StrEnum):
    """Messages that get handled in some way."""

    ACK = "0d 02 43 ba 0a"
    DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"
    KEEPALIVE = "0d b0 01 6a 00 43 a0 0a"
