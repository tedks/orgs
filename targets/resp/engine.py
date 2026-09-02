"""command-engine — command frame in, reply frame out.

TRACER BULLET (M1): PING only. Hardened to the full C2 contract
(contracts/C2-command-engine.md) by the command-engine work package.
"""

from codec import SimpleString, Error, Integer, BulkString


class Engine:
    """Deterministic: same command sequence, same replies. Owns the
    key-value store."""

    def __init__(self):
        self.store = {}  # dict[bytes, bytes]

    def execute(self, command):
        args = command.value  # list[BulkString]
        name_value = args[0].value

        # Guard against nil command-name BulkString (RESP nil)
        if name_value is None:
            return Error("ERR unknown command ''")

        name = name_value.lower()  # bytes, case-insensitive

        # Dispatch to command handlers
        if name == b"ping":
            return self._ping(args[1:])
        elif name == b"echo":
            return self._echo(args[1:])
        elif name == b"get":
            return self._get(args[1:])
        elif name == b"set":
            return self._set(args[1:])
        elif name == b"del":
            return self._del(args[1:])
        elif name == b"incr":
            return self._incr(args[1:])
        else:
            # Unknown command
            cmd_name = name.decode('utf-8', errors='replace')
            return Error(f"ERR unknown command '{cmd_name}'")

    def _ping(self, args):
        """PING [msg] -> PONG or msg (as bulk string)"""
        if len(args) == 0:
            return SimpleString("PONG")
        elif len(args) == 1:
            return BulkString(args[0].value)
        else:
            return Error("ERR wrong number of arguments for 'ping' command")

    def _echo(self, args):
        """ECHO msg -> msg (as bulk string)"""
        if len(args) == 1:
            return BulkString(args[0].value)
        else:
            return Error("ERR wrong number of arguments for 'echo' command")

    def _get(self, args):
        """GET key -> value or nil"""
        if len(args) != 1:
            return Error("ERR wrong number of arguments for 'get' command")

        key = args[0].value
        if key in self.store:
            return BulkString(self.store[key])
        else:
            return BulkString(None)

    def _set(self, args):
        """SET key value -> OK"""
        if len(args) != 2:
            return Error("ERR wrong number of arguments for 'set' command")

        key = args[0].value
        value = args[1].value
        self.store[key] = value
        return SimpleString("OK")

    def _del(self, args):
        """DEL key [key ...] -> count of deleted keys"""
        if len(args) == 0:
            return Error("ERR wrong number of arguments for 'del' command")

        count = 0
        for arg in args:
            key = arg.value
            if key in self.store:
                del self.store[key]
                count += 1
        return Integer(count)

    def _incr(self, args):
        """INCR key -> incremented value as integer"""
        if len(args) != 1:
            return Error("ERR wrong number of arguments for 'incr' command")

        key = args[0].value

        if key in self.store:
            value = self.store[key]
            try:
                num = int(value.decode('ascii'))
                new_value = num + 1
                self.store[key] = str(new_value).encode('ascii')
                return Integer(new_value)
            except (ValueError, UnicodeDecodeError):
                return Error("ERR value is not an integer or out of range")
        else:
            self.store[key] = b"1"
            return Integer(1)
