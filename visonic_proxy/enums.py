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
