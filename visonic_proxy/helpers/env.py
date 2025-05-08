"""*NIX env helper functions."""

import logging
import os

from ..const import LOGGER_NAME, Config, MsgLogLevel
from ..logger import VPLogger

_LOGGER = logging.getLogger(LOGGER_NAME)


def is_running_as_addon() -> bool:
    """Return if running as HA addon."""
    return any(env == "SUPERVISOR_TOKEN" for env in os.environ)


def match_env_to_config(config: str) -> str | None:
    """Get matching env to config ignoring case."""
    for env in os.environ:
        if env.casefold() == config.casefold():
            return env
    return None


def get_env_var(env_var_name: str) -> str | None:
    """Get env var by name."""
    return os.environ.get(env_var_name)


def process_env_vars(log_class: VPLogger) -> Config:
    """Set config from env vars if exist."""
    default_config = Config
    ignore_env_configs = []

    configs = [
        (attr, getattr(default_config, attr))
        for attr in vars(default_config)
        if not callable(getattr(default_config, attr))
        and not attr.startswith("__")
        and attr not in ignore_env_configs
    ]
    for config in configs:
        if (
            os.environ.get(config[0])
            or os.environ.get(config[0].lower())
            or os.environ.get(config[0].upper())
        ):
            try:
                env = match_env_to_config(config[0])
                value = os.environ.get(env)
                new_value = value

                # Translate env value
                if config[0] == "LOG_LEVEL":
                    value = value.lower()
                    if value == "critical":
                        new_value = logging.CRITICAL
                    elif value == "error":
                        new_value = logging.ERROR
                    elif value == "warning":
                        new_value = logging.WARNING
                    elif value == "info":
                        new_value = logging.INFO
                    elif value == "debug":
                        new_value = logging.DEBUG

                    log_class.logger.setLevel(new_value)
                elif isinstance(value, str):
                    if value.lower() == "true":
                        new_value = True
                    elif value.lower() == "false":
                        new_value = False

                _LOGGER.debug(
                    "Setting %s to %s from env",
                    config[0],
                    value.upper() if isinstance(value, str) else value,
                    extra=MsgLogLevel.L1,
                )
                setattr(default_config, config[0], new_value)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.warning("Error setting %s to %s - %s", config[0], value, ex)
                continue
    return default_config
