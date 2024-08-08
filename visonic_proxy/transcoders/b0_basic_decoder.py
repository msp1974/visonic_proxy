"""Basic B0 Message Decoder."""


class B0BasicDecoder:
    """Basic decoder for getting info from messages."""

    def decode(self, msg: bytes) -> dict[str, str | list[str]]:
        """Decode B0 message and return data."""
        command = msg[3:4].hex()
        if hasattr(self, f"b0_{command}_decoder"):
            return getattr(self, f"b0_{command}_decoder")(msg)

    def b0_0f_decoder(self, msg: bytes) -> dict[str, str]:
        """Extract certain status values in a 0f message.

        0d b0 03 0f 0b 19 07 0f 00 00 01 00 01 00 80 96 43 a6 0a
        Byte 13 is panel state
        """
        return {"status": int.from_bytes(msg[13:14])}

    def b0_24_decoder(self, msg: bytes) -> dict[str, str]:
        """Extract certain status values in a 24 message.

        0d b0 03 24 1a ff 08 ff 15 02 00 00 00 00 00 00 00 11 04 0f 08 08 18 14 05 01 00 80 00 00 97 43 2d 0a
        Byte 26 is panel state
        """
        return {"status": int.from_bytes(msg[26:27])}

    def b0_51_decoder(self, msg: bytes) -> dict[str, list[str]]:
        """Extract the list of asks in a 51 message.

        0d b0 03 51 08 ff 08 ff 03 18 24 4b 20 43 fc 0a
        Byte 8 is how many
        Bytes 9 -> count is list
        """
        count = int.from_bytes(msg[8:9])
        if count:
            return {"commands": [cmd.to_bytes().hex() for cmd in msg[9 : 9 + count]]}
        return {"commands": []}
