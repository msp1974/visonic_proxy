"""Enums."""

from enum import IntEnum, StrEnum


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
    BUMP = "0d 09 f6 0a"  # Alarm does ACK
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
