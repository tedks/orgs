#!/usr/bin/env python3
"""resp_smoke_rawsocket.py — raw-socket conformance substitute for
bench/conformance/resp_conformance.sh, for environments where `redis-cli`
(the frozen exam's external grader) is not installed.

This is NOT a replacement for the frozen exam and does not modify it —
resp_conformance.sh remains the spec of "conformant" for this sprint
(docs/specs/2026-09-02-resp-tracer.md, Conformance grading). This script
exists only because this environment lacks `redis-cli`
(`command -v redis-cli` fails here as of the resp-tracer pilot sprint,
2026-09-02) and the RUNBOOK still requires evidence the server behaves
correctly. It asserts the same goal-command behaviors by speaking raw
RESP2 directly over a socket instead of going through a real client.

Because it is not a real, unmodified `redis-cli`, a pass here is weaker
evidence than a pass of the frozen exam — it proves the server's own
wire behavior is self-consistent with what this script encodes as RESP2,
not that a real Redis client is satisfied. Report which one actually ran
whenever citing a result.

Usage: resp_smoke_rawsocket.py <server-cmd...>
  <server-cmd...> starts the server; it MUST accept `--port <port>`.
  Example: resp_smoke_rawsocket.py python3 targets/resp/server.py

Exit: 0 all assertions pass · 1 an assertion failed · 2 harness/setup error.
"""
import random
import socket
import subprocess
import sys
import time


def encode_array(*args: bytes) -> bytes:
    """Encode a command as a proper RESP array of bulk strings (never the
    inline form) — matches the frozen exam's own encoding choice."""
    out = f"*{len(args)}\r\n".encode()
    for a in args:
        out += f"${len(a)}\r\n".encode() + a + b"\r\n"
    return out


class Conn:
    """One persistent socket connection; reads exactly the frames it's
    told to expect by scanning RESP framing (not a general parser — this
    harness is intentionally independent of targets/resp/codec.py, so a
    bug in that module can't make its own exam agree with itself)."""

    def __init__(self, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.buf = b""

    def send(self, *args: bytes) -> None:
        self.sock.sendall(encode_array(*args))

    def send_raw(self, data: bytes) -> None:
        self.sock.sendall(data)

    def _fill(self) -> None:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("server closed the connection unexpectedly")
        self.buf += chunk

    def _read_line(self) -> bytes:
        while b"\r\n" not in self.buf:
            self._fill()
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def read_reply(self):
        """Read exactly one RESP2 reply, return (type_sigil, value)."""
        line = self._read_line()
        sigil, rest = line[:1], line[1:]
        if sigil in (b"+", b"-"):
            return sigil, rest.decode("utf-8")
        if sigil == b":":
            return sigil, int(rest)
        if sigil == b"$":
            length = int(rest)
            if length == -1:
                return sigil, None
            while len(self.buf) < length + 2:
                self._fill()
            payload, self.buf = self.buf[:length], self.buf[length + 2 :]
            return sigil, payload
        if sigil == b"*":
            count = int(rest)
            if count == -1:
                return sigil, None
            return sigil, [self.read_reply() for _ in range(count)]
        raise ValueError(f"unrecognized reply sigil: {sigil!r} (line={line!r})")

    def close(self) -> None:
        self.sock.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: resp_smoke_rawsocket.py <server-cmd...>", file=sys.stderr)
        return 2

    port = random.randint(20000, 40000)
    proc = subprocess.Popen([*sys.argv[1:], "--port", str(port)])
    passed = 0
    failed = 0

    def check(desc: str, expected, actual) -> None:
        nonlocal passed, failed
        if expected == actual:
            passed += 1
        else:
            failed += 1
            print(f"FAIL: {desc} — expected {expected!r} got {actual!r}", file=sys.stderr)

    try:
        ready = False
        for _ in range(50):
            try:
                probe = socket.create_connection(("127.0.0.1", port), timeout=0.2)
                probe.close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        if not ready:
            print(f"smoke: server did not become ready on port {port}", file=sys.stderr)
            return 2

        c = Conn(port)

        c.send(b"PING")
        check("PING", (b"+", "PONG"), c.read_reply())

        c.send(b"ECHO", b"hello")
        check("ECHO hello", (b"$", b"hello"), c.read_reply())

        c.send(b"SET", b"k", b"v")
        check("SET k v", (b"+", "OK"), c.read_reply())

        c.send(b"GET", b"k")
        check("GET k", (b"$", b"v"), c.read_reply())

        c.send(b"GET", b"nope")
        check("GET missing (nil)", (b"$", None), c.read_reply())

        c.send(b"DEL", b"k")
        check("DEL k", (b":", 1), c.read_reply())

        c.send(b"DEL", b"nope")
        check("DEL missing", (b":", 0), c.read_reply())

        c.send(b"SET", b"n", b"10")
        c.read_reply()
        c.send(b"INCR", b"n")
        check("SET n 10 / INCR", (b":", 11), c.read_reply())

        # binary-safe value: embedded CR LF and a NUL byte.
        payload = b"a\r\nb\x00c"
        c.send(b"SET", b"bin", payload)
        c.read_reply()
        c.send(b"GET", b"bin")
        check("binary-safe SET/GET (CRLF+NUL)", (b"$", payload), c.read_reply())

        c.send(b"SET", b"s", b"abc")
        c.read_reply()
        c.send(b"INCR", b"s")
        sigil, _ = c.read_reply()
        check("INCR non-integer errs", b"-", sigil)

        c.send(b"SET", b"onlykey")
        sigil, _ = c.read_reply()
        check("SET wrong arity errs", b"-", sigil)

        c.close()

        # True pipelining: both requests written before either reply is
        # read, on one connection (mirrors the frozen exam's own
        # /dev/tcp probe, but via a real socket client instead of bash).
        c2 = Conn(port)
        c2.send_raw(encode_array(b"PING") + encode_array(b"PING"))
        r1 = c2.read_reply()
        r2 = c2.read_reply()
        check("pipelined PING;PING (one conn)", [(b"+", "PONG"), (b"+", "PONG")], [r1, r2])
        c2.close()

    except Exception as exc:  # noqa: BLE001 — smoke harness, report and exit 2
        print(f"smoke: harness error: {exc!r}", file=sys.stderr)
        return 2
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"smoke (raw-socket, redis-cli unavailable): {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
