"""Constants."""

from enum import StrEnum
import logging

PROXY_MODE = True
LOG_LEVEL = logging.INFO
LOG_TO_FILE = True
LOG_FILES_TO_KEEP = 10

# 1 connection/disconnection info only
# 2 same as 1 plus sent messages
# 3 same as 2 plus sent ACKs
# 4 same as 3 plus received messages
# 5 same as 4 plus ack waiting messages and builder messages
# 6 full debug
MESSAGE_LOG_LEVEL = 5


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
ALARM_MONITOR_SENDS_KEEPALIVES = False
ACK_B0_03_MESSAGES = False
SEND_E0_MESSAGES = True

FILTER_STD_COMMANDS = []
FILTER_B0_COMMANDS = []


TEXT_UNKNOWN = "UNKNOWN"

VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
DUH = "DUH"
NAK = "NAK"

STATUS_COMMAND = "e0"
ACTION_COMMAND = "e1"


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


NO_WAIT_FOR_ACK_MESSAGES = [ManagedMessages.STOP]
