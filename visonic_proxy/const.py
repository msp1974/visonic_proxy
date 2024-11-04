"""Constants."""

from collections import namedtuple
from enum import IntEnum, StrEnum
import logging


class Config:
    """Config settings."""

    # 1 connection/disconnection info only
    # 2 same as 1 plus sent messages
    # 3 same as 2 plus sent ACKs
    # 4 same as 3 plus received messages
    # 5 same as 4 plus ack waiting messages and builder messages
    LOG_LEVEL = logging.INFO
    MESSAGE_LOG_LEVEL = 3
    LOG_FILE = ""
    LOG_FILES_TO_KEEP = 10

    PROXY_MODE = True

    WEBSOCKET_MODE = False  # Use websocket client instead of IP socket client

    VISONIC_HOST = "52.58.105.181"
    MESSAGE_PORT = 5001
    ALARM_MONITOR_PORT = 5002
    WEBSOCKET_PORT = 8082

    VISONIC_RECONNECT_INTERVAL = 10  # Freq CM will reconnect Visonic after disconnect
    KEEPALIVE_TIMER = 32  # Send Keepalive if no messages in 30 seconds
    WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
    ACK_TIMEOUT = 5  # How long to wait for ACK before continuing

    STEALTH_MODE_TIMEOUT = (
        10  # If no received message from Monitor connection, timeout stealth mode.
    )

    DOWNLOAD_MODE_SETS_STEALTH = (
        True  # If monitor asks for download mode, set stealth too.  Reverse true
    )

    ALARM_MONITOR_SENDS_ACKS = True  # Monitor sends ACKS
    ALARM_MONITOR_NEEDS_ACKS = True  # Monitor expects ACKS
    ALARM_MONITOR_SENDS_KEEPALIVES = False  # Monitor handles keepalives
    ALARM_MONITOR_SEND_TO_ALL = (
        True  # When sending to monitor connection, send to all clients
    )

    ACK_B0_03_MESSAGES = False  # If CM should ACK B0 messages
    SEND_E0_MESSAGES = True  # Send E0 status messages to Alarm Montitor clients

    MATCH_ACK_MSG_ID = False  # Match msg id for all ACKs - experimental

    STATUS_COMMAND = "e0"  # Message type for status messages
    ACTION_COMMAND = "e1"  # Message type for action commands

    FILTER_STD_COMMANDS = ["0b"]  # Std messages from Monitor of these types are dropped
    FILTER_B0_COMMANDS = []  # B0 messages from Monitor of these types are dropped
    NO_WAIT_FOR_ACK_MESSAGES = []  # These messages will not wait for ACKs

    INVALID_MESSAGE_THRESHOLD = (
        2  # Number of times a 06 response is received before marking command invalid
    )


TEXT_UNKNOWN = "UNKNOWN"
VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
ACK = "ACK"
DUH = "DUH"
NAK = "NAK"


class Mode(StrEnum):
    """Mode setting."""

    STEALTH = "stealth"
    DOWNLOAD = "download"


class ManagerStatus(StrEnum):
    """Connection manager status enum."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"


class ConnectionType(StrEnum):
    """Connection Type enum."""

    CLIENT = "client"
    SERVER = "server"


class ConnectionName(StrEnum):
    """Connection name enum."""

    CM = "ConnMgr"
    ALARM = "Alarm"
    VISONIC = "Visonic"
    ALARM_MONITOR = "HASS"


class ConnectionPriority(IntEnum):
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

    PL_ACK = "0d 02 43 ba 0a"
    ACK = "0d 02 fd 0a"
    DISCONNECT_MESSAGE = "0d ad 0a 00 00 00 00 00 00 00 00 00 43 05 0a"
    HELLO = "0d 06 f9 0a"
    KEEPALIVE = "0d b0 01 6a 00 43 a0 0a"
    DOWNLOAD = "0d 09 f6 0a"  # Alarm does ACK
    STOP = "0d 0b f4 0a"  # Alarm doesnt ACK
    EXIT_DOWNLOAD_MODE = "0d 0f f0 0a"  # Alarm does ACK
    # Don't really know what this is but alarm sends when HA send a STOP
    # message.
    OUT_OF_DOWNLOAD_MODE = "0d 08 f7 0a"


class MsgLogLevel:
    """Message log level."""

    L1 = {"msglevel": 1}
    L2 = {"msglevel": 2}
    L3 = {"msglevel": 3}
    L4 = {"msglevel": 4}
    L5 = {"msglevel": 5}


class Colour:
    """Logging colours."""

    green = "\x1b[1;32m"
    blue = "\x1b[1;36m"
    grey = "\x1b[1;38m"
    yellow = "\x1b[1;33m"
    red = "\x1b[1;31m"
    purple = "\x1b[1;35m"
    reset = "\x1b[0m"


# prefix and siffix filters are OR'd
KeywordColour = namedtuple(
    "KeywordColour", "keyword prefix_filter suffix_filter colour"
)

KEYWORD_COLORS = [
    KeywordColour(ConnectionName.ALARM, ["->", "<< "], ["->"], Colour.green),
    KeywordColour(ConnectionName.ALARM_MONITOR, ["->", "<< "], ["->"], Colour.purple),
    KeywordColour(ConnectionName.VISONIC, ["->", "<< "], ["->"], Colour.yellow),
    KeywordColour(ConnectionName.CM, ["->", "<< "], ["->"], Colour.blue),
]
