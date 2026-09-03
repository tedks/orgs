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

# Resource limits (sized for a tracer). Without these, a huge declared bulk
# length or array count buffers unboundedly (OOM), a huge length digit-string
# reaches int()'s conversion limit (ValueError -> crash), and deeply nested
# arrays exhaust the recursion stack (RecursionError -> crash). The codec
# converts all of these into ProtocolError so nothing but ProtocolError ever
# escapes feed() — the server's firewall stays clean.
MAX_LEN_DIGITS = 19          # an int64/length is <= 19 digits; more can't be valid and would hit int()'s limit
MAX_BULK = 16 * 1024 * 1024  # a single bulk string (16 MiB)
MAX_MULTIBULK = 64 * 1024    # elements in one array
MAX_DEPTH = 32               # array nesting depth
MAX_BUFFER = 32 * 1024 * 1024  # unparsed bytes retained between feeds


def _read_line(buf: bytes, start: int):
    """Return (line_bytes, new_pos) for the CRLF-terminated line beginning
    at `start` (not including the CRLF); new_pos is just past the CRLF.
    Raises _NeedMoreData if no CRLF is present yet in `buf[start:]`."""
    end = buf.find(b"\r\n", start)
    if end == -1:
        raise _NeedMoreData()
    return buf[start:end], end + 2


def _parse_int(raw: bytes, what: str) -> int:
    # Cap digit count BEFORE int(): int() on a >4300-digit string raises
    # ValueError (Py3.11+ CVE-2020-10735 mitigation), which would escape as a
    # non-ProtocolError and crash the server. A valid length/count/int64 is
    # well under MAX_LEN_DIGITS.
    if not _INT_RE.match(raw) or len(raw.lstrip(b"-")) > MAX_LEN_DIGITS:
        raise ProtocolError(f"invalid {what}: {raw!r}")
    return int(raw)


def _decode_text(raw: bytes, what: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"invalid {what} (not utf-8): {raw!r}") from exc


def _parse_frame(buf: bytes, pos: int, depth: int = 0):
    """Return (Frame, new_pos) for the frame beginning at `pos`. Raises
    _NeedMoreData if `buf[pos:]` is a proper prefix of a frame, or
    ProtocolError if it can never be completed into a valid frame."""
    if depth > MAX_DEPTH:
        raise ProtocolError("array nesting exceeds %d" % MAX_DEPTH)
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
        if length > MAX_BULK:
            raise ProtocolError("bulk string length %d exceeds limit" % length)
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
        if count > MAX_MULTIBULK:
            raise ProtocolError("array length %d exceeds limit" % count)
        elements = []
        cur = new_pos
        for _ in range(count):
            frame, cur = _parse_frame(buf, cur, depth + 1)
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

    def has_pending(self) -> bool:
        """True iff bytes of an incomplete frame are still buffered — the
        server uses this to keep a receive deadline running for a partial
        frame rather than resetting it every time some frame completes."""
        return len(self._buf) > 0

    def feed(self, data: bytes):
        self._buf += data
        frames = []
        while True:
            try:
                frame, consumed = _parse_frame(self._buf, 0)
            except _NeedMoreData:
                # A prefix is buffered. Bound how much we retain, so a huge
                # declared length or a slow drip of an incomplete frame can't
                # grow the buffer without limit (OOM).
                if len(self._buf) > MAX_BUFFER:
                    raise ProtocolError("unparsed buffer exceeds %d bytes" % MAX_BUFFER)
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
