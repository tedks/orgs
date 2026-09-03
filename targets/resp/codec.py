"""resp-codec: bytes <-> RESP2 frames. No socket, no store, no command knowledge.

Tracer bullet (lead-built, M1): the RESP2 grammar (all five frame types,
incremental feed/encode, binary-safe bulk strings) is real, since a fake
shortcut here wouldn't prove contract C1 composes with the other entities.
What's left crude / for wp-codec: malformed-input coverage beyond the raise,
and the boundary tests in tests/test_codec_contract.py.

Contract: ../../contracts/C1-resp-codec.md
"""
from dataclasses import dataclass
from typing import List, Optional, Union


class ProtocolError(Exception):
    """Malformed input. Connection-fatal per C1 — caller must not feed() again."""


@dataclass
class SimpleString:
    value: str


@dataclass
class Error:
    value: str


@dataclass
class Integer:
    value: int


@dataclass
class BulkString:
    value: Optional[bytes]  # None == RESP2 null bulk string ($-1\r\n)


@dataclass
class Array:
    value: Optional[List["Frame"]]  # None == RESP2 null array (*-1\r\n)


Frame = Union[SimpleString, Error, Integer, BulkString, Array]


class RespCodec:
    """Holds parse state for exactly one connection's inbound byte stream."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> List[Frame]:
        self._buf += data
        frames: List[Frame] = []
        while True:
            frame, consumed = _try_parse(self._buf)
            if frame is None:
                break
            frames.append(frame)
            self._buf = self._buf[consumed:]
        return frames


def _find_crlf(buf: bytes) -> int:
    return buf.find(b"\r\n")


def _try_parse(buf: bytes):
    """Returns (frame, bytes_consumed) or (None, 0) if buf holds no complete frame yet."""
    if not buf:
        return None, 0
    t = buf[0:1]
    if t == b"+":
        return _parse_line(buf, SimpleString)
    if t == b"-":
        return _parse_line(buf, Error)
    if t == b":":
        return _parse_integer(buf)
    if t == b"$":
        return _parse_bulk(buf)
    if t == b"*":
        return _parse_array(buf)
    raise ProtocolError(f"unknown RESP type byte: {t!r}")


def _parse_line(buf: bytes, cls):
    idx = _find_crlf(buf)
    if idx == -1:
        return None, 0
    return cls(buf[1:idx].decode("utf-8", errors="strict")), idx + 2


def _parse_integer(buf: bytes):
    idx = _find_crlf(buf)
    if idx == -1:
        return None, 0
    try:
        n = int(buf[1:idx])
    except ValueError as e:
        raise ProtocolError(f"invalid integer frame: {buf[1:idx]!r}") from e
    return Integer(n), idx + 2


def _parse_bulk(buf: bytes):
    idx = _find_crlf(buf)
    if idx == -1:
        return None, 0
    try:
        length = int(buf[1:idx])
    except ValueError as e:
        raise ProtocolError(f"invalid bulk length: {buf[1:idx]!r}") from e
    if length == -1:
        return BulkString(None), idx + 2
    if length < -1:
        raise ProtocolError(f"negative bulk length: {length}")
    start = idx + 2
    end = start + length
    if len(buf) < end + 2:
        return None, 0
    if buf[end:end + 2] != b"\r\n":
        raise ProtocolError("bulk string payload not terminated by CRLF")
    return BulkString(buf[start:end]), end + 2


def _parse_array(buf: bytes):
    idx = _find_crlf(buf)
    if idx == -1:
        return None, 0
    try:
        count = int(buf[1:idx])
    except ValueError as e:
        raise ProtocolError(f"invalid array length: {buf[1:idx]!r}") from e
    if count == -1:
        return Array(None), idx + 2
    if count < -1:
        raise ProtocolError(f"negative array length: {count}")
    pos = idx + 2
    items: List[Frame] = []
    for _ in range(count):
        frame, consumed = _try_parse(buf[pos:])
        if frame is None:
            return None, 0  # incomplete; re-parse from scratch on next feed()
        items.append(frame)
        pos += consumed
    return Array(items), pos


def encode(frame: Frame) -> bytes:
    if isinstance(frame, SimpleString):
        return b"+" + frame.value.encode("utf-8") + b"\r\n"
    if isinstance(frame, Error):
        return b"-" + frame.value.encode("utf-8") + b"\r\n"
    if isinstance(frame, Integer):
        return b":" + str(frame.value).encode("ascii") + b"\r\n"
    if isinstance(frame, BulkString):
        if frame.value is None:
            return b"$-1\r\n"
        return b"$" + str(len(frame.value)).encode("ascii") + b"\r\n" + frame.value + b"\r\n"
    if isinstance(frame, Array):
        if frame.value is None:
            return b"*-1\r\n"
        out = [b"*", str(len(frame.value)).encode("ascii"), b"\r\n"]
        out.extend(encode(item) for item in frame.value)
        return b"".join(out)
    raise ProtocolError(f"cannot encode frame: {frame!r}")
