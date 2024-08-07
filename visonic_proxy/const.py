"""Constants."""

import logging

LOG_LEVEL = logging.INFO
LOG_TO_FILE = True
LOG_FILES_TO_KEEP = 10

# 1 connection/disconnection info only
# 2 same as 1 plus sent messages
# 3 same as 2 plus sent ACKs
# 4 same as 3 plus received messages
# 5 same as 4 plus ack waiting messages and builder messages
MESSAGE_LOG_LEVEL = 5


class Config:
    """Config settings."""

    PROXY_MODE = True

    VISONIC_HOST = "52.58.105.181"
    MESSAGE_PORT = 5001
    ALARM_MONITOR_PORT = 5002

    VISONIC_RECONNECT_INTERVAL = 10  # Freq CM will reconnect Visonic after disconnect
    KEEPALIVE_TIMER = 30  # Send Keepalive if no messages in 30 seconds
    WATHCHDOG_TIMEOUT = 120  # If no received message on connection for 120s, kill it.
    ACK_TIMEOUT = 5  # How long to wait for ACK before continuing

    STEALTH_MODE_TIMEOUT = 30  # Max time to be in Stealth mode before exiting

    ALARM_MONITOR_SENDS_ACKS = True  # Monitor sends ACKS
    ALARM_MONITOR_NEEDS_ACKS = True  # Monitor expects ACKS
    ALARM_MONITOR_SENDS_KEEPALIVES = False  # Monitor handles keepalives

    ACK_B0_03_MESSAGES = False  # If CM should ACK B0 messages
    SEND_E0_MESSAGES = True  # Send E0 status messages to Alarm Montitor clients

    MATCH_ACK_MSG_ID = False  # Match msg id for all ACKs - experimental

    STATUS_COMMAND = "e0"  # Message type for status messages
    ACTION_COMMAND = "e1"  # Message type for action commands

    FILTER_STD_COMMANDS = ["0b"]  # Std messages from Monitor of these types are dropped
    FILTER_B0_COMMANDS = []  # B0 messages from Monitor of these types are dropped
    NO_WAIT_FOR_ACK_MESSAGES = []  # These messages will not wait for ACKs


TEXT_UNKNOWN = "UNKNOWN"
VIS_ACK = "VIS-ACK"
VIS_BBA = "VIS-BBA"
ADM_CID = "*ADM-CID"
ADM_ACK = "*ACK"
DUH = "DUH"
NAK = "NAK"
