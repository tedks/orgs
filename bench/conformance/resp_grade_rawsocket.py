#!/usr/bin/env python3
"""Neutral RESP conformance grader over raw sockets.

An independent grader for the RESP tracer, used when `redis-cli` (the frozen
exam's external client) is not installed. It encodes the SAME assertion set as
bench/conformance/resp_conformance.sh — the spec's frozen exam — but drives the
server with hand-built RESP2 frames over one TCP connection, so no client
library is required. It is authored from the spec, independent of any server
implementation, so it grades every regime's build on identical terms.

Usage: resp_grade_rawsocket.py <server-cmd...>
  The server command must accept `--port <port>` (or read $PORT) and listen.
Exit: 0 all pass, 1 an assertion failed, 2 harness/setup error.
"""
import os, socket, subprocess, sys, time


def enc(*parts):
    """Encode a RESP2 array of bulk strings from bytes/str parts."""
    out = b"*%d\r\n" % len(parts)
    for p in parts:
        if isinstance(p, str):
            p = p.encode()
        out += b"$%d\r\n%s\r\n" % (len(p), p)
    return out


class Conn:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.buf = b""

    def send(self, frame):
        self.s.sendall(frame)

    def _fill(self):
        self.s.settimeout(5)
        chunk = self.s.recv(65536)
        if not chunk:
            raise EOFError("server closed the connection")
        self.buf += chunk

    def read_reply(self):
        """Parse one RESP2 reply; return a python value.

        +simple -> str, -error -> ('ERR', text), :int -> int,
        $bulk -> bytes or None, *array -> list.
        """
        while b"\r\n" not in self.buf:
            self._fill()
        line, self.buf = self.buf.split(b"\r\n", 1)
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            return ("ERR", rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n == -1:
                return None
            while len(self.buf) < n + 2:
                self._fill()
            data, self.buf = self.buf[:n], self.buf[n + 2:]
            return data
        if t == b"*":
            n = int(rest)
            if n == -1:
                return None
            return [self.read_reply() for _ in range(n)]
        raise ValueError("bad reply type %r" % t)

    def cmd(self, *parts):
        self.send(enc(*parts))
        return self.read_reply()


def main():
    if len(sys.argv) < 2:
        print("usage: resp_grade_rawsocket.py <server-cmd...>", file=sys.stderr)
        return 2
    port = 20000 + (os.getpid() % 20000)
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(sys.argv[1:] + ["--port", str(port)], env=env)
    try:
        # wait for the port
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            print("grade: server did not become ready", file=sys.stderr)
            return 2

        p = f = 0

        def check(desc, want, got):
            nonlocal p, f
            if got == want:
                p += 1
            else:
                f += 1
                print(f"FAIL: {desc} — want {want!r} got {got!r}", file=sys.stderr)

        c = Conn(port)
        check("PING", "PONG", c.cmd("PING"))
        check("ECHO", b"hello", c.cmd("ECHO", "hello"))
        check("SET k v", "OK", c.cmd("SET", "k", "v"))
        check("GET k", b"v", c.cmd("GET", "k"))
        check("GET missing -> nil", None, c.cmd("GET", "nope"))
        check("DEL k -> 1", 1, c.cmd("DEL", "k"))
        check("DEL missing -> 0", 0, c.cmd("DEL", "nope"))
        check("SET n 10", "OK", c.cmd("SET", "n", "10"))
        check("INCR n -> 11", 11, c.cmd("INCR", "n"))
        check("INCR fresh -> 1", 1, c.cmd("INCR", "fresh"))
        # binary-safe: embedded CR LF and NUL
        binval = b"a\r\nb\x00c"
        check("SET bin", "OK", c.cmd("SET", "bin", binval))
        check("GET bin round-trips", binval, c.cmd("GET", "bin"))
        # errors are RESP error replies
        r = c.cmd("SET", "s", "abc")
        r = c.cmd("INCR", "s")
        check("INCR non-integer -> error", "ERR", r[0] if isinstance(r, tuple) else r)
        r = c.cmd("SET", "onlykey")
        check("SET wrong arity -> error", "ERR", r[0] if isinstance(r, tuple) else r)
        # pipelining: two PINGs written before either read, one connection
        c.send(enc("PING") + enc("PING"))
        check("pipelined PING #1", "PONG", c.read_reply())
        check("pipelined PING #2", "PONG", c.read_reply())

        print(f"grade: {p} passed, {f} failed")
        return 0 if f == 0 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
