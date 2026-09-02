#!/usr/bin/env python3
"""Raw-socket smoke test for targets/resp/server.py.

Written because `redis-cli` is not installed in this environment (the
conformance exam at bench/conformance/resp_conformance.sh hard-requires it
and exits 2 without it). This drives the server directly over RESP2 on a
single TCP connection -- no external client -- covering the same ground the
frozen exam asserts: PING, ECHO, GET, SET, DEL, INCR, binary-safe values
(embedded CR/LF/NUL), wrong-arity errors, non-integer INCR, and true
pipelining (both requests written before either reply is read).

Usage: python3 smoke_test.py [--port N]  (spawns its own server subprocess
if --port is omitted; otherwise connects to an already-running server).

Exit: 0 all checks pass, 1 a check failed.
"""
import argparse
import socket
import subprocess
import sys
import time


def encode_command(*args):
    """Encode args as a RESP2 multibulk command (the real wire format, same
    as what redis-cli sends -- not the inline form)."""
    parts = [b"*" + str(len(args)).encode() + b"\r\n"]
    for a in args:
        b = a if isinstance(a, (bytes, bytearray)) else str(a).encode()
        parts.append(b"$" + str(len(b)).encode() + b"\r\n" + b + b"\r\n")
    return b"".join(parts)


class RespClient:
    """A tiny RESP2 reply parser over a live socket, buffered like the
    server's own reader so partial TCP reads are handled correctly."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def _fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("server closed connection")
        self.buf += chunk

    def _read_line(self):
        while b"\r\n" not in self.buf:
            self._fill()
        idx = self.buf.index(b"\r\n")
        line, self.buf = self.buf[:idx], self.buf[idx + 2:]
        return line

    def _read_exact(self, n):
        while len(self.buf) < n:
            self._fill()
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def read_reply(self):
        line = self._read_line()
        kind, payload = line[0:1], line[1:]
        if kind == b"+":
            return ("simple", payload)
        if kind == b"-":
            return ("error", payload)
        if kind == b":":
            return ("integer", int(payload))
        if kind == b"$":
            n = int(payload)
            if n == -1:
                return ("bulk", None)
            data = self._read_exact(n)
            crlf = self._read_exact(2)
            assert crlf == b"\r\n", "missing trailing CRLF on bulk reply"
            return ("bulk", data)
        raise ValueError("unrecognized reply type byte: %r" % kind)

    def command(self, *args):
        self.sock.sendall(encode_command(*args))
        return self.read_reply()


passed = 0
failed = 0


def check(desc, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok  - %s" % desc)
    else:
        failed += 1
        print("FAIL - %s%s" % (desc, (": " + detail) if detail else ""), file=sys.stderr)


def wait_for_port(host, port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def run_checks(host, port):
    with socket.create_connection((host, port), timeout=5) as sock:
        c = RespClient(sock)

        check("PING", c.command("PING") == ("simple", b"PONG"))
        check("ECHO hello", c.command("ECHO", "hello") == ("bulk", b"hello"))
        check("SET k v", c.command("SET", "k", "v") == ("simple", b"OK"))
        check("GET k", c.command("GET", "k") == ("bulk", b"v"))
        check("GET missing -> nil", c.command("GET", "nope") == ("bulk", None))
        check("DEL k -> 1", c.command("DEL", "k") == ("integer", 1))
        check("DEL missing -> 0", c.command("DEL", "nope") == ("integer", 0))

        check("SET n 10", c.command("SET", "n", "10") == ("simple", b"OK"))
        check("INCR n -> 11", c.command("INCR", "n") == ("integer", 11))
        check("INCR fresh key -> 1", c.command("INCR", "freshctr") == ("integer", 1))

        # binary-safe value: embedded CR LF and a NUL byte
        binval = b"a\r\nb\x00c"
        check("SET bin (binary-safe)", c.command("SET", "binkey", binval) == ("simple", b"OK"))
        kind, data = c.command("GET", "binkey")
        check("GET bin round-trips exactly", kind == "bulk" and data == binval,
              "got %r" % (data,))

        # wrong arity errors
        kind, _ = c.command("SET", "onlykey")
        check("SET wrong arity -> error", kind == "error")
        kind, _ = c.command("GET", "a", "b")
        check("GET wrong arity -> error", kind == "error")
        kind, _ = c.command("ECHO")
        check("ECHO wrong arity -> error", kind == "error")
        kind, _ = c.command("DEL")
        check("DEL wrong arity -> error", kind == "error")
        kind, _ = c.command("PING", "a", "b")
        check("PING wrong arity -> error", kind == "error")

        # non-integer INCR
        check("SET s abc", c.command("SET", "s", "abc") == ("simple", b"OK"))
        kind, msg = c.command("INCR", "s")
        check("INCR non-integer -> error", kind == "error", "got %r %r" % (kind, msg))
        check("INCR error mentions 'integer'", b"integer" in msg.lower())

        # unknown command doesn't crash the server
        kind, _ = c.command("BOGUSCMD", "x")
        check("unknown command -> error (server survives)", kind == "error")

    # true pipelining: both requests written before either reply is read,
    # on one connection -- open a fresh connection for a clean sequence.
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(encode_command("PING") + encode_command("PING"))
        c = RespClient(sock)
        r1 = c.read_reply()
        r2 = c.read_reply()
        check("pipelined PING;PING both PONG", r1 == ("simple", b"PONG") and r2 == ("simple", b"PONG"),
              "got %r %r" % (r1, r2))

    # sequential correctness still holds after pipelining on a fresh conn
    with socket.create_connection((host, port), timeout=5) as sock:
        c = RespClient(sock)
        check("post-pipeline PING still fine", c.command("PING") == ("simple", b"PONG"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None,
                     help="connect to an already-running server on this port; "
                          "if omitted, spawn our own server subprocess")
    args = ap.parse_args()

    proc = None
    port = args.port
    try:
        if port is None:
            port = 24177
            server_path = __file__.replace("smoke_test.py", "server.py")
            proc = subprocess.Popen([sys.executable, server_path, "--port", str(port)])
            if not wait_for_port("127.0.0.1", port, timeout=5.0):
                print("smoke_test: server did not come up on port %d" % port, file=sys.stderr)
                sys.exit(2)
        run_checks("127.0.0.1", port)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("smoke_test: %d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
