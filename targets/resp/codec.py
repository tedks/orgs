"""resp-codec — bytes <-> RESP2 frames.

Hardened to the full C1 contract (contracts/C1-resp-codec.md): the five
RESP2 frame types, an incremental `Parser.feed(bytes) -> list[Frame]`, and
a complete `encode(Frame) -> bytes`. No socket, no store, no command
knowledge — this module only ever talks about bytes and Frame objects.
"""

import re

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProtocolError(Exception):
    """Malformed RESP input. Connection-fatal per C1.

    The contract makes no promise about parser state after this is raised,
    and none about how much of the malformed input was consumed — callers
    must not call feed() again on the same Parser instance afterward.
    """


class _NeedMoreData(Exception):
    """Internal only: the buffer holds a prefix of a frame, not malformed
    input. Never escapes Parser.feed()."""


# ---------------------------------------------------------------------------
# Frame data model
# ---------------------------------------------------------------------------


class SimpleString:
    def __init__(self, value: str):
        self.value = value  # str, no embedded \r or \n

    def __eq__(self, other):
        return isinstance(other, SimpleString) and self.value == other.value

    def __repr__(self):
        return f"SimpleString({self.value!r})"


class Error:
    def __init__(self, value: str):
        self.value = value  # str, no embedded \r or \n

    def __eq__(self, other):
        return isinstance(other, Error) and self.value == other.value

    def __repr__(self):
        return f"Error({self.value!r})"


class Integer:
    def __init__(self, value: int):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, Integer) and self.value == other.value

    def __repr__(self):
        return f"Integer({self.value!r})"


class BulkString:
    def __init__(self, value):
        self.value = value  # bytes | None (None = RESP nil bulk string)

    def __eq__(self, other):
        return isinstance(other, BulkString) and self.value == other.value

    def __repr__(self):
        return f"BulkString({self.value!r})"


class Array:
    def __init__(self, value):
        self.value = value  # list[Frame] | None (None = RESP nil array)

    def __eq__(self, other):
        return isinstance(other, Array) and self.value == other.value

    def __repr__(self):
        return f"Array({self.value!r})"


# ---------------------------------------------------------------------------
# Parsing (bytes -> Frame)
# ---------------------------------------------------------------------------

# RESP integers (lengths, counts, :-values): optional leading '-', then one
# or more digits. Deliberately stricter than Python's int() — no leading
# '+', no whitespace, no underscore grouping, no floats.
_INT_RE = re.compile(rb"^-?\d+$")


def _read_line(buf: bytes, start: int):
    """Return (line_bytes, new_pos) for the CRLF-terminated line beginning
    at `start` (not including the CRLF); new_pos is just past the CRLF.
    Raises _NeedMoreData if no CRLF is present yet in `buf[start:]`."""
    end = buf.find(b"\r\n", start)
    if end == -1:
        raise _NeedMoreData()
    return buf[start:end], end + 2


def _parse_int(raw: bytes, what: str) -> int:
    if not _INT_RE.match(raw):
        raise ProtocolError(f"invalid {what}: {raw!r}")
    return int(raw)


def _decode_text(raw: bytes, what: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"invalid {what} (not utf-8): {raw!r}") from exc


def _parse_frame(buf: bytes, pos: int):
    """Return (Frame, new_pos) for the frame beginning at `pos`. Raises
    _NeedMoreData if `buf[pos:]` is a proper prefix of a frame, or
    ProtocolError if it can never be completed into a valid frame."""
    if pos >= len(buf):
        raise _NeedMoreData()

    sigil = buf[pos : pos + 1]

    if sigil == b"+":
        raw, new_pos = _read_line(buf, pos + 1)
        return SimpleString(_decode_text(raw, "simple string")), new_pos

    if sigil == b"-":
        raw, new_pos = _read_line(buf, pos + 1)
        return Error(_decode_text(raw, "error")), new_pos

    if sigil == b":":
        raw, new_pos = _read_line(buf, pos + 1)
        return Integer(_parse_int(raw, "integer")), new_pos

    if sigil == b"$":
        raw_len, new_pos = _read_line(buf, pos + 1)
        length = _parse_int(raw_len, "bulk string length")
        if length == -1:
            return BulkString(None), new_pos
        if length < -1:
            raise ProtocolError(f"invalid bulk string length: {length}")
        payload_end = new_pos + length
        terminator_end = payload_end + 2
        if terminator_end > len(buf):
            raise _NeedMoreData()
        if buf[payload_end:terminator_end] != b"\r\n":
            raise ProtocolError(
                "bulk string length does not match delivered payload boundary"
            )
        return BulkString(buf[new_pos:payload_end]), terminator_end

    if sigil == b"*":
        raw_count, new_pos = _read_line(buf, pos + 1)
        count = _parse_int(raw_count, "array length")
        if count == -1:
            return Array(None), new_pos
        if count < -1:
            raise ProtocolError(f"invalid array length: {count}")
        elements = []
        cur = new_pos
        for _ in range(count):
            frame, cur = _parse_frame(buf, cur)
            elements.append(frame)
        return Array(elements), cur

    raise ProtocolError(f"invalid RESP type sigil: {sigil!r}")


class Parser:
    """Incremental RESP2 parser, one instance per connection.

    Stateful: retains whatever trailing bytes are not yet a complete frame
    between feed() calls, so a frame may arrive split across arbitrarily
    many chunks (including one byte per call). Not thread-safe. Not
    reusable after feed() raises ProtocolError — tear the connection down
    instead of calling feed() again.
    """

    def __init__(self):
        self._buf = b""

    def feed(self, data: bytes):
        self._buf += data
        frames = []
        while True:
            try:
                frame, consumed = _parse_frame(self._buf, 0)
            except _NeedMoreData:
                break
            frames.append(frame)
            self._buf = self._buf[consumed:]
        return frames


# ---------------------------------------------------------------------------
# Encoding (Frame -> bytes)
# ---------------------------------------------------------------------------


def encode(frame) -> bytes:
    """Serialize exactly one frame. Pure, side-effect free. Never raises
    for a well-formed instance of the five frame types (see C1's
    Intentionally unspecified re: SimpleString/Error \\r\\n content)."""
    if isinstance(frame, SimpleString):
        return b"+" + frame.value.encode("utf-8") + b"\r\n"

    if isinstance(frame, Error):
        return b"-" + frame.value.encode("utf-8") + b"\r\n"

    if isinstance(frame, Integer):
        return b":" + str(frame.value).encode("ascii") + b"\r\n"

    if isinstance(frame, BulkString):
        if frame.value is None:
            return b"$-1\r\n"
        return (
            b"$" + str(len(frame.value)).encode("ascii") + b"\r\n"
            + frame.value + b"\r\n"
        )

    if isinstance(frame, Array):
        if frame.value is None:
            return b"*-1\r\n"
        header = b"*" + str(len(frame.value)).encode("ascii") + b"\r\n"
        return header + b"".join(encode(element) for element in frame.value)

    raise TypeError(f"encode: not a Frame instance: {frame!r}")
