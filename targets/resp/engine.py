"""command-engine: command frame in, reply frame out. Owns the key-value store.
No bytes, no sockets — imports the Frame data model from codec.py per C2
rather than redefining it.

Tracer bullet (lead-built, M1): only PING is implemented, to prove the
codec<->engine<->server wiring composes. ECHO/GET/SET/DEL/INCR, arity
errors, and non-integer INCR are wp-engine's work (contract C2).

Contract: ../../contracts/C2-command-engine.md
"""
from typing import List

from codec import BulkString, Error, Frame, Integer, SimpleString


class Engine:
    """One instance is the whole server's key-value store (not per-connection)."""

    def __init__(self) -> None:
        self._store: dict[bytes, bytes] = {}

    def execute(self, command: List[bytes]) -> Frame:
        if not command:
            return Error("ERR wrong number of arguments")
        name = command[0].decode("utf-8", errors="replace").upper()
        if name == "PING":
            return self._ping(command)
        if name == "ECHO":
            return self._echo(command)
        if name == "GET":
            return self._get(command)
        if name == "SET":
            return self._set(command)
        if name == "DEL":
            return self._del(command)
        if name == "INCR":
            return self._incr(command)
        return Error(f"ERR unknown command '{name}'")

    def _ping(self, command: List[bytes]) -> Frame:
        if len(command) == 1:
            return SimpleString("PONG")
        if len(command) == 2:
            return BulkString(command[1])
        return Error("ERR wrong number of arguments for 'ping' command")

    def _echo(self, command: List[bytes]) -> Frame:
        if len(command) != 2:
            return Error("ERR wrong number of arguments for 'echo' command")
        return BulkString(command[1])

    def _get(self, command: List[bytes]) -> Frame:
        if len(command) != 2:
            return Error("ERR wrong number of arguments for 'get' command")
        key = command[1]
        value = self._store.get(key)
        return BulkString(value)

    def _set(self, command: List[bytes]) -> Frame:
        if len(command) != 3:
            return Error("ERR wrong number of arguments for 'set' command")
        key = command[1]
        value = command[2]
        self._store[key] = value
        return SimpleString("OK")

    def _del(self, command: List[bytes]) -> Frame:
        if len(command) != 2:
            return Error("ERR wrong number of arguments for 'del' command")
        key = command[1]
        if key in self._store:
            del self._store[key]
            return Integer(1)
        return Integer(0)

    def _incr(self, command: List[bytes]) -> Frame:
        if len(command) != 2:
            return Error("ERR wrong number of arguments for 'incr' command")
        key = command[1]
        # Get current value (or 0 if absent)
        if key in self._store:
            current_bytes = self._store[key]
        else:
            current_bytes = b"0"
        # Parse as integer
        try:
            current_value = int(current_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Error("ERR value is not an integer or out of range")
        # Increment and store
        new_value = current_value + 1
        self._store[key] = str(new_value).encode("utf-8")
        return Integer(new_value)
