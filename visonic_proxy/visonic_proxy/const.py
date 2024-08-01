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

# TO BE
# 1 connection/disconnection info
# 2 same as 1 plus messages
# 3 same as 2 plus ACKs
# 4 same as 3 plus ?
MESSAGE_LOG_LEVEL = 2


VISONIC_HOST = "52.58.105.181"
MESSAGE_PORT = 5001
ALARM_MONITOR_PORT = 5002
VISONIC_MONITOR_PORT = 5003
VISONIC_RECONNECT_INTERVAL = 10
KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
ACK_TIMEOUT = 5  # How long to wait for ACK before continuing


ALARM_MONITOR_SENDS_ACKS = True
ALARM_MONITOR_NEEDS_ACKS = True
ACK_B0_03_MESSAGES = True
SEND_E0_MESSAGES = False


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

    CM = "ConnectionManager"
    ALARM = "Alarm"
    VISONIC = "Visonic"
    ALARM_MONITOR = "HA"
    VISONIC_MONITOR = "Visonic_Monitor"


class ConnectionSourcePriority(IntEnum):
    """Message priority for source."""

    CM = 3
    ALARM = 1
    VISONIC = 2
    ALARM_MONITOR = 3


class ConnectionStatus(IntEnum):
    """Connection status."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTING = 2


class ManagedMessages(StrEnum):
    """Messages that get handled in some way."""

    ACK = "0d 02 43 ba 0a"
    DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"
    HELLO = "0d 06 f9 0a"
    KEEPALIVE = "0d b0 01 6a 00 43 a0 0a"
    DOWNLOAD_MODE = "0d 09 f6 0a"  # Alarm does ACK
    STOP = "0d 0b f4 0a"  # Alarm doesnt ACK
    EXIT_DOWNLOAD_MODE = "0d 0f f0 0a"  # Alarm does ACK
    # Don't really know what this is but alarm sends when HA send a STOP
    # message.
    OUT_OF_DOWNLOAD_MODE = "0d 08 f7 0a"
