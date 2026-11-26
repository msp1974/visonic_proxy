"""Independent PowerLink 3.1 msg_id translation between Alarm and Visonic links."""

from collections import OrderedDict


class MessageIdMapper:
    """Maintains independent msg_id sequences for Alarm and Visonic links.

    Prevents Home Assistant injected commands from desynchronising the msg_id
    sequence expected by the Visonic PowerManage server and vice versa.
    """

    def __init__(self, max_entries: int = 256):
        """Initialise mapper with bounded correlation tables."""
        self._max_entries = max_entries
        self._alarm_to_visonic: OrderedDict[int, int] = OrderedDict()
        self._visonic_to_alarm: OrderedDict[int, int] = OrderedDict()
        self.alarm_last_msg_id: int = 0
        self.visonic_last_msg_id: int = 0

    @staticmethod
    def _increment(current: int) -> int:
        """Increment 4-digit PowerLink msg_id wrapping at 10000 (skipping 0)."""
        next_id = (current + 1) % 10000
        return 1 if next_id == 0 else next_id

    def _put_bounded(self, mapping: OrderedDict[int, int], key: int, value: int):
        """Store key/value in an OrderedDict evicting oldest entries past limit."""
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > self._max_entries:
            mapping.popitem(last=False)

    def observe_alarm_msg_id(self, msg_id: int):
        """Record latest msg_id observed on the Alarm link."""
        if msg_id:
            self.alarm_last_msg_id = msg_id

    def observe_visonic_msg_id(self, msg_id: int):
        """Record latest msg_id observed on the Visonic link."""
        if msg_id:
            self.visonic_last_msg_id = msg_id

    def next_alarm_msg_id(self) -> int:
        """Allocate next msg_id to send to the Alarm panel."""
        self.alarm_last_msg_id = self._increment(self.alarm_last_msg_id)
        return self.alarm_last_msg_id

    def next_visonic_msg_id(self) -> int:
        """Allocate next msg_id to send to the Visonic server."""
        self.visonic_last_msg_id = self._increment(self.visonic_last_msg_id)
        return self.visonic_last_msg_id

    def map_visonic_to_alarm(self, visonic_msg_id: int) -> int:
        """Translate an outgoing Visonic->Alarm VIS-BBA msg_id and record mapping."""
        self.observe_visonic_msg_id(visonic_msg_id)
        if self.alarm_last_msg_id == 0 and visonic_msg_id:
            alarm_msg_id = visonic_msg_id
            self.alarm_last_msg_id = alarm_msg_id
        else:
            alarm_msg_id = self.next_alarm_msg_id()
        self._put_bounded(self._alarm_to_visonic, alarm_msg_id, visonic_msg_id)
        return alarm_msg_id

    def resolve_alarm_ack_for_visonic(self, alarm_msg_id: int) -> int | None:
        """Look up original Visonic msg_id for an Alarm->Visonic VIS-ACK."""
        return self._alarm_to_visonic.get(alarm_msg_id)

    def map_alarm_to_visonic(self, alarm_msg_id: int) -> int:
        """Translate an outgoing Alarm->Visonic VIS-BBA msg_id and record mapping."""
        self.observe_alarm_msg_id(alarm_msg_id)
        if self.visonic_last_msg_id == 0 and alarm_msg_id:
            visonic_msg_id = alarm_msg_id
            self.visonic_last_msg_id = visonic_msg_id
        else:
            visonic_msg_id = self.next_visonic_msg_id()
        self._put_bounded(self._visonic_to_alarm, visonic_msg_id, alarm_msg_id)
        return visonic_msg_id

    def resolve_visonic_ack_for_alarm(self, visonic_msg_id: int) -> int | None:
        """Look up original Alarm msg_id for a Visonic->Alarm VIS-ACK."""
        return self._visonic_to_alarm.get(visonic_msg_id)

    def reset_visonic(self):
        """Reset Visonic-side correlation state on Visonic disconnect."""
        self._alarm_to_visonic.clear()
        self._visonic_to_alarm.clear()
        self.visonic_last_msg_id = 0

    def reset_alarm(self):
        """Reset all correlation state on Alarm disconnect."""
        self._alarm_to_visonic.clear()
        self._visonic_to_alarm.clear()
        self.alarm_last_msg_id = 0
        self.visonic_last_msg_id = 0
