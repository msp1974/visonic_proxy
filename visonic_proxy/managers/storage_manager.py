import logging
from typing import Any

from ..transcoders.b0_decoder import MessageType
from ..transcoders.helpers import get_lookup_value
from ..transcoders.refs import B0CommandName, Command35Settings

_LOGGER = logging.getLogger(__name__)

STATUS = "status"
SETTINGS = "settings"
EPROM = "eprom"


class DataStore:
    def __init__(self):
        self._data: dict[str, dict | str] = {}
        self._raw_data: dict[str, dict | str] = {}
        self._raw_eprom_data: list[int] = [None] * 65535

    def _combine_dict(self, d1: dict, d2: dict):
        d = d1
        for key in list(d2.keys()):
            if key in d:
                if isinstance(d2[key], list):
                    d[key].extend(d2[key])
                else:
                    d[key].append(d2[key])
            else:
                d[key] = d2[key]

        return d

    def _rebuild_pages(self, paged_data: dict):
        dict_result = {}
        list_result = []
        for page_data in paged_data.values():
            if isinstance(page_data, dict):
                dict_result = self._combine_dict(dict_result, page_data)
            elif isinstance(page_data, list):
                list_result.extend(page_data)

        if dict_result:
            return dict_result
        return list_result

    def store(
        self,
        msg_class: str,
        msg_type: int,
        cmd: str,
        setting: int,
        page: int,
        data: dict | str,
        raw_data: Any,
    ) -> bool:
        """Store data and return if data has changed."""

        # Store raw data
        has_changed = self.raw_store(msg_class, cmd, setting, page, raw_data)

        # If setting not 0 then either 35 or 42 command.
        # Store under settings header
        if msg_class == SETTINGS:
            self._store_settings(msg_type, cmd, setting, page, data)
        elif msg_class == STATUS:
            self._store_status(msg_type, cmd, page, data)
        elif msg_class == EPROM:
            if not self._data.get(EPROM):
                self._data[EPROM] = {}

            if not self._data[EPROM].get(setting):
                self._data[EPROM][setting] = {}

            if not self._data[EPROM][setting].get(page):
                self._data[EPROM][setting][page] = {}

            self._data[EPROM][setting][page] = data

            # Store to raw eprom
            pos = (setting * 255) + page
            eprom_data = data.split(" ")
            for idx, e in enumerate(eprom_data):
                self._raw_eprom_data[pos + idx] = e

        else:
            if not self._data.get(msg_class):
                self._data[msg_class] = {}

            if not self._data[msg_class].get(cmd):
                self._data[msg_class][cmd] = {}

            self._data[msg_class][cmd][setting] = data

        return has_changed

    def store_eprom(self, position: int, data: str):
        """Store eprom data in raw data store."""
        # Store to raw eprom
        # _LOGGER.info("EPROM STORE: POSITION: %s", position)
        eprom_data = data.split(" ")
        for idx, e in enumerate(eprom_data):
            self._raw_eprom_data[position + idx] = e

    def _store_status(self, msg_type: int, cmd: str, page: int, data: Any):
        """Store status data."""

        # Set keys
        if not self._data.get(STATUS):
            self._data[STATUS] = {}

        command_name = f"{cmd}_{get_lookup_value(B0CommandName, cmd)}"
        if not self._data[STATUS].get(command_name):
            self._data[STATUS][command_name] = {}

        if page == 0:
            self._data[STATUS][command_name] = data
        elif msg_type == MessageType.PAGED_RESPONSE:
            if page == 1:
                # First page, clear any paged data
                self._data[STATUS][command_name] = {"pages": {}}

            if not self._data[STATUS][command_name].get("pages"):
                self._data[STATUS][command_name]["pages"] = {}

            # Sometimes page number is wrong
            if page == 255:
                page = (
                    1
                    if not self._data[STATUS][command_name]["pages"]
                    else self._data[STATUS][command_name]["pages"].keys()[-1] + 1
                )

            self._data[STATUS][command_name]["pages"][page] = data
        elif msg_type == MessageType.RESPONSE:
            # If pre-existing paged data
            if isinstance(self._data[STATUS][command_name], dict) and self._data[
                STATUS
            ][command_name].get("pages"):
                # Add last page to pages
                self._data[STATUS][command_name]["pages"][page] = data

                # Rebuild data
                self._data[STATUS][command_name] = self._rebuild_pages(
                    self._data[STATUS][command_name]["pages"]
                )

            else:
                self._data[STATUS][command_name] = data

    def _store_settings(
        self, msg_type: int, cmd: str, setting: int, page: int, data: Any
    ):
        """Store settings (cmd 35 and 42) data.

        This may have conflicts with 35 and 42 being in same key but in the vast
        majority of cases, they provide same data.
        """
        key = f"{SETTINGS}{cmd}"
        if not self._data.get(key):
            self._data[key] = {}

        setting_name = f"{setting}_{get_lookup_value(Command35Settings, setting)}"

        if not self._data[key].get(setting_name):
            self._data[key][setting_name] = {}

        if msg_type == MessageType.PAGED_RESPONSE:
            # Sometimes page number is wrong
            if isinstance(self._data[key][setting_name], dict) and not self._data[key][
                setting_name
            ].get("pages"):
                self._data[key][setting_name]["pages"] = {}

            if page == 255:
                page = (
                    1
                    if not self._data[key][setting_name]["pages"]
                    else self._data[key][setting_name]["pages"].keys()[-1] + 1
                )

            if page == 1:
                # First page, clear any paged data
                self._data[key][setting_name] = {}
                self._data[key][setting_name]["pages"] = {}
            self._data[key][setting_name]["pages"][page] = data
        elif msg_type == MessageType.RESPONSE:
            # If pre-existing paged data
            if isinstance(self._data[key][setting_name], dict) and self._data[key][
                setting_name
            ].get("pages"):
                # Add last page to pages
                self._data[key][setting_name]["pages"][page] = data

                # Rebuild data
                self._data[key][setting_name] = self._rebuild_pages(
                    self._data[key][setting_name]["pages"]
                )

            else:
                self._data[key][setting_name] = data

    def raw_store(
        self,
        msg_class: str,
        cmd: str,
        setting: int | None = None,
        page: int | None = None,
        data: Any | None = None,
    ) -> bool:
        """Store raw data and return if changed."""

        has_changed = False

        if msg_class == EPROM:
            return None

        key = msg_class
        if cmd in ["35", "42"]:
            key = f"{SETTINGS}{cmd}"

        if not self._raw_data.get(key):
            self._raw_data[key] = {}

        if cmd in ["35", "42"]:
            setting_name = f"{setting}_{get_lookup_value(Command35Settings, setting)}"
            if not self._raw_data[key].get(setting_name):
                self._raw_data[key][setting_name] = {}

            # Store raw data
            has_changed = self.log_raw_changed(key, setting_name, page, data)
            if isinstance(data, dict):
                for idx, values in data.items():
                    if not self._raw_data[key][setting_name].get(page):
                        self._raw_data[key][setting_name][page] = {}
                    self._raw_data[key][setting_name][page][idx] = values
            else:
                self._raw_data[key][setting_name][page] = data
        else:
            command_name = f"{cmd}_{get_lookup_value(B0CommandName, cmd)}"
            if not self._raw_data[key].get(command_name):
                self._raw_data[key][command_name] = {}

            # Store data
            has_changed = self.log_raw_changed(key, command_name, page, data)
            if isinstance(data, dict):
                for idx, values in data.items():
                    if not self._raw_data[key][command_name].get(page):
                        self._raw_data[key][command_name][page] = {}
                    self._raw_data[key][command_name][page][idx] = values
            else:
                self._raw_data[key][command_name][page] = data
            # self._raw_data[key][command_name][page] = data

        return has_changed

    def log_raw_changed(self, key: str, cmd_setting: str, page: int, data: Any) -> bool:
        """Has there been an update to this."""
        try:
            if self._raw_data[key][cmd_setting][page] != data:
                _LOGGER.debug(
                    "%s\nOLD: %s\nNEW: %s",
                    f"{key}-{cmd_setting}",
                    self._raw_data[key][cmd_setting][page],
                    data,
                )
                return True
        except KeyError:
            return False

    def get_all_data(self, raw_data: bool = False) -> dict:
        """Get all stored data."""
        if raw_data:
            return self._raw_data
        return self._data

    def get_status(self, key: str) -> dict | str | list:
        """Get data from data store."""
        try:
            return self._data[STATUS][key]
        except KeyError:
            return None

    def get_setting(self, key: str, s42: bool = False) -> dict | str | list:
        """Get data from data store."""
        try:
            if s42:
                return self._data["settings42"][key]
            return self._data["settings35"][key]
        except KeyError:
            return None

    def get_eprom_setting2(
        self, page: int, index: int, length: int | None = None
    ) -> str | dict | None:
        """Get eprom data."""
        try:
            data = self._data[EPROM][page][index]
            # if length and len(data) < length:
            #    return None
            return data
        except (AttributeError, KeyError, TypeError):
            return None

    def get_eprom_setting(
        self, position: int, length: int | None = None
    ) -> str | dict | None:
        """Get eprom data."""
        raw_data = self._raw_eprom_data[position : position + length]
        # _LOGGER.info("GET EPROM: POS: %s, DATA: %s", position, raw_data)
        if None not in raw_data:
            data = " ".join(str(x) for x in raw_data)
            return data
        return None

    def get_eprom(self):
        return self._raw_eprom_data
