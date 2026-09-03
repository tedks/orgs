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
        return Error(f"ERR unknown command '{name}'")

    def _ping(self, command: List[bytes]) -> Frame:
        if len(command) == 1:
            return SimpleString("PONG")
        if len(command) == 2:
            return BulkString(command[1])
        return Error("ERR wrong number of arguments for 'ping' command")
