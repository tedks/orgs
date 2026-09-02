"""command-engine — command frame in, reply frame out.

TRACER BULLET (M1): PING only. Hardened to the full C2 contract
(contracts/C2-command-engine.md) by the command-engine work package.
"""

from codec import SimpleString


class Engine:
    """Deterministic: same command sequence, same replies. Owns the
    key-value store (none needed yet for PING)."""

    def execute(self, command):
        args = command.value  # list[BulkString]
        name = args[0].value.upper()
        if name == b"PING":
            return SimpleString("PONG")
        raise NotImplementedError(
            f"tracer stub: command {name!r} not wired; "
            "command-engine work package must add ECHO/GET/SET/DEL/INCR"
        )
