"""resp-codec — bytes <-> RESP2 frames.

TRACER BULLET (M1): a crude, PING-only slice proving the contracts compose
end to end. Hardened to the full C1 contract
(contracts/C1-resp-codec.md) by the resp-codec work package — see that
file's TODOs before treating this as done.
"""


class ProtocolError(Exception):
    """Malformed RESP input. Connection-fatal per C1."""


class SimpleString:
    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, SimpleString) and self.value == other.value

    def __repr__(self):
        return f"SimpleString({self.value!r})"


class BulkString:
    def __init__(self, value):
        self.value = value  # bytes | None (None = RESP nil bulk string)

    def __eq__(self, other):
        return isinstance(other, BulkString) and self.value == other.value

    def __repr__(self):
        return f"BulkString({self.value!r})"


class Array:
    def __init__(self, value):
        self.value = value  # list[Frame] | None

    def __eq__(self, other):
        return isinstance(other, Array) and self.value == other.value

    def __repr__(self):
        return f"Array({self.value!r})"


class Parser:
    """TRACER STUB — not the real incremental parser.

    Assumes each feed() call is handed exactly one complete RESP array of
    bulk strings (a client request), does no cross-call buffering of
    partial frames, and does not recognize Error/Integer frames or
    malformed input. The resp-codec work package replaces this with the
    real `feed(bytes) -> [Frame]` incremental semantics from C1.
    """

    def feed(self, data: bytes):
        if not data:
            return []
        lines = data.split(b"\r\n")
        assert lines[0][:1] == b"*", "tracer stub: only array requests"
        n = int(lines[0][1:])
        args = []
        i = 1
        for _ in range(n):
            assert lines[i][:1] == b"$", "tracer stub: only bulk-string args"
            length = int(lines[i][1:])
            args.append(lines[i + 1][:length])
            i += 2
        return [Array([BulkString(a) for a in args])]


def encode(frame) -> bytes:
    """TRACER STUB — only SimpleString encoding wired."""
    if isinstance(frame, SimpleString):
        return b"+" + frame.value.encode("ascii") + b"\r\n"
    raise NotImplementedError(
        "tracer stub: encode() only handles SimpleString; "
        "resp-codec work package must add Error/Integer/BulkString/Array"
    )
