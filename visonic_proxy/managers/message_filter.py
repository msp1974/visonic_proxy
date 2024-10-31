"""Filters messages from Alarm Monitor to not be sent to Alarm."""

from visonic_proxy.proxy import Proxy


def is_filtered(proxy: Proxy, data: bytes) -> bool:
    """Return if should filter this message."""

    command = data[1:2].hex()

    # Filter B0 commands
    if command == "b0":
        b0_command = data[3:4].hex()
        if b0_command in proxy.config.FILTER_B0_COMMANDS:
            return True
        return False

    # Filter std commands
    if command in proxy.config.FILTER_STD_COMMANDS:
        return True

    return False
