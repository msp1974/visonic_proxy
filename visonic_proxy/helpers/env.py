"""*NIX env and Home Assistant add-on options helper functions."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..const import LOGGER_NAME, Config, MsgLogLevel
from ..logger import VPLogger

_LOGGER = logging.getLogger(LOGGER_NAME)

ADDON_OPTIONS_PATH = "/data/options.json"
SENSITIVE_CONFIG_KEYS = frozenset({"WEBSOCKET_AUTH_KEY"})

_LOG_LEVEL_MAP = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def is_running_as_addon() -> bool:
    """Return if running as HA addon."""
    return "SUPERVISOR_TOKEN" in os.environ


def redact_config_value(key: str, value: Any) -> Any:
    """Mask sensitive configuration values for safe logging."""
    if key.upper() in SENSITIVE_CONFIG_KEYS and value:
        return "***REDACTED***"
    return value


def match_env_to_config(config: str) -> str | None:
    """Get matching env to config ignoring case."""
    for env in os.environ:
        if env.casefold() == config.casefold():
            return env
    return None


def get_env_var(env_var_name: str) -> str | None:
    """Get env var by name."""
    if env := match_env_to_config(env_var_name):
        return os.environ.get(env)
    return None


def load_addon_options(options_path: str = ADDON_OPTIONS_PATH) -> dict[str, Any]:
    """Load Home Assistant add-on options.json when available."""
    path = Path(options_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError) as ex:
        _LOGGER.warning("Error reading add-on options from %s: %s", options_path, ex)
    return {}


def _coerce_config_value(key: str, value: Any, default_value: Any) -> Any:
    """Coerce an incoming option/env value to match the target Config attribute type."""
    if key == "LOG_LEVEL":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            level_key = value.strip().lower()
            if level_key in _LOG_LEVEL_MAP:
                return _LOG_LEVEL_MAP[level_key]
        raise ValueError(f"Invalid LOG_LEVEL: {value!r}")

    if isinstance(default_value, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        raise ValueError(f"Invalid boolean for {key}: {value!r}")

    if isinstance(default_value, int):
        if isinstance(value, bool):
            raise TypeError(f"Invalid integer for {key}: {value!r}")
        return int(value)

    if isinstance(default_value, float):
        if isinstance(value, bool):
            raise TypeError(f"Invalid float for {key}: {value!r}")
        return float(value)

    return value


def process_env_vars(
    log_class: VPLogger | None = None,
    options_path: str = ADDON_OPTIONS_PATH,
) -> Config:
    """Build a Config instance populated from add-on options.json and env vars."""
    config_instance = Config()
    config_attrs = [
        (attr, getattr(Config, attr))
        for attr in vars(Config)
        if not callable(getattr(Config, attr)) and not attr.startswith("__")
    ]

    addon_options = load_addon_options(options_path) if options_path else {}
    addon_options_folded = {k.casefold(): v for k, v in addon_options.items()}

    for key, default_value in config_attrs:
        source = None
        raw_value: Any = None

        if key.casefold() in addon_options_folded:
            raw_value = addon_options_folded[key.casefold()]
            source = "addon options"

        env_name = match_env_to_config(key)
        if env_name is not None and os.environ.get(env_name) not in (None, ""):
            raw_value = os.environ[env_name]
            source = "env"

        if source is None:
            continue

        try:
            new_value = _coerce_config_value(key, raw_value, default_value)
            if key == "LOG_LEVEL" and log_class is not None:
                log_class.logger.setLevel(new_value)

            _LOGGER.debug(
                "Setting %s to %s from %s",
                key,
                redact_config_value(key, new_value),
                source,
                extra=MsgLogLevel.L1,
            )
            setattr(config_instance, key, new_value)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning(
                "Error setting %s to %s - %s",
                key,
                redact_config_value(key, raw_value),
                ex,
            )

    return config_instance
