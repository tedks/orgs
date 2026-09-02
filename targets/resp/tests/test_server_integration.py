"""Integration tests for the server work package
(work-packages/server.md) — owned scope, authored by the worker (no
frozen boundary-test file for this package, unlike codec/engine).

These exercise `targets/resp/server.py` the way the conformance harness
will: launched as a real subprocess, listening on a real TCP port, driven
by a raw-socket client that speaks RESP2 directly — never by importing
server.py's internals. That's deliberate: the point is to prove the
process's observable socket behavior, not to unit-test functions inside
it.

Run: python3 -m unittest discover -s targets/resp/tests
(or just this file: python3 -m unittest targets.resp.tests.test_server_integration -v)
"""

import os
import socket
import subprocess
import sys
import time
import unittest

_HERE = os.path.dirname(__file__)
_TARGET_DIR = os.path.join(_HERE, "..")
_SERVER_PY = os.path.join(_TARGET_DIR, "server.py")


def encode_array(*args: bytes) -> bytes:
    """Encode a command as a proper RESP2 array of bulk strings."""
    out = f"*{len(args)}\r\n".encode()
    for a in args:
        out += f"${len(a)}\r\n".encode() + a + b"\r\n"
    return out


class RespConn:
    """A raw-socket RESP2 client connection, independent of
    targets/resp/codec.py on purpose — a bug in the codec module must not
    be able to make this harness agree with itself."""

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
        """Read exactly one RESP2 reply, return (sigil: bytes, value)."""
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

    def expect_eof(self, timeout: float = 2.0) -> None:
        """Assert the server closes this connection (recv() -> b"")."""
        self.sock.settimeout(timeout)
        chunk = self.sock.recv(65536)
        if chunk != b"":
            raise AssertionError(f"expected EOF, got more bytes: {chunk!r}")

    def close(self) -> None:
        self.sock.close()


class ServerProcess:
    """Launches targets/resp/server.py as a real subprocess on an
    ephemeral port and waits for it to accept connections. Context
    manager so tests can't leak a server process on failure."""

    def __init__(self):
        self.port = None
        self.proc = None

    def __enter__(self):
        # Ephemeral port: bind port 0 to let the OS choose a free one,
        # then hand that number to the server subprocess. Small race
        # (the OS could reuse the port before the subprocess binds it),
        # accepted for a test harness — matches the pattern used by
        # bench/conformance/resp_smoke_rawsocket.py (random port + retry
        # loop), just with OS-assigned freedom instead of a random guess.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        self.port = port
        self.proc = subprocess.Popen(
            [sys.executable, _SERVER_PY, "--port", str(port)],
            cwd=_TARGET_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._wait_ready()
        return self

    def _wait_ready(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                out, err = self.proc.communicate()
                raise RuntimeError(
                    f"server exited early (code {self.proc.returncode}): "
                    f"stdout={out!r} stderr={err!r}"
                )
            try:
                probe = socket.create_connection(("127.0.0.1", self.port), timeout=0.2)
                probe.close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"server did not become ready on port {self.port}")

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def connect(self, timeout: float = 5.0) -> RespConn:
        return RespConn(self.port, timeout=timeout)

    def __exit__(self, exc_type, exc, tb):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
            if self.proc.stdout:
                self.proc.stdout.close()
            if self.proc.stderr:
                self.proc.stderr.close()


class TestPipelining(unittest.TestCase):
    def test_two_pipelined_requests_both_replies_correct_and_in_order(self):
        with ServerProcess() as srv:
            c = srv.connect()
            try:
                # Both requests written before either reply is read — the
                # graded pipelining behavior (spec: Conformance grading).
                c.send_raw(encode_array(b"PING") + encode_array(b"ECHO", b"hi"))
                r1 = c.read_reply()
                r2 = c.read_reply()
                self.assertEqual(r1, (b"+", "PONG"))
                self.assertEqual(r2, (b"$", b"hi"))
            finally:
                c.close()

    def test_pipelined_requests_split_across_recv_boundaries(self):
        # Same as above but the two encoded commands are written as many
        # small chunks, forcing the server's recv()/Parser.feed() loop to
        # reassemble frames across arbitrary chunk boundaries rather than
        # assuming one recv() == one command.
        with ServerProcess() as srv:
            c = srv.connect()
            try:
                payload = encode_array(b"PING") + encode_array(b"ECHO", b"hi")
                for i in range(len(payload)):
                    c.sock.sendall(payload[i : i + 1])
                r1 = c.read_reply()
                r2 = c.read_reply()
                self.assertEqual(r1, (b"+", "PONG"))
                self.assertEqual(r2, (b"$", b"hi"))
            finally:
                c.close()


class TestSequentialCommands(unittest.TestCase):
    def test_multiple_sequential_commands_on_one_connection(self):
        with ServerProcess() as srv:
            c = srv.connect()
            try:
                c.send(b"SET", b"k", b"v1")
                self.assertEqual(c.read_reply(), (b"+", "OK"))

                c.send(b"GET", b"k")
                self.assertEqual(c.read_reply(), (b"$", b"v1"))

                c.send(b"SET", b"k", b"v2")
                self.assertEqual(c.read_reply(), (b"+", "OK"))

                c.send(b"GET", b"k")
                self.assertEqual(c.read_reply(), (b"$", b"v2"))

                c.send(b"DEL", b"k")
                self.assertEqual(c.read_reply(), (b":", 1))
            finally:
                c.close()


class TestMalformedFrameTeardown(unittest.TestCase):
    def test_malformed_frame_closes_connection_without_crashing_server(self):
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                # Bad type sigil: not one of + - : $ * — ProtocolError,
                # connection-fatal per C1.
                bad.send_raw(b"!invalid\r\n")
                bad.expect_eof()
            finally:
                bad.close()

            self.assertTrue(srv.is_alive(), "server process crashed on malformed input")

            # A fresh connection right after must still work.
            good = srv.connect()
            try:
                good.send(b"PING")
                self.assertEqual(good.read_reply(), (b"+", "PONG"))
            finally:
                good.close()

    def test_bad_bulk_string_length_boundary_closes_connection(self):
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                # Declares a 3-byte bulk string ("abc") but the two bytes
                # where the terminating CRLF must land ("XY") aren't
                # \r\n — a length/payload-boundary mismatch, all bytes
                # present (not an incomplete-frame case), so feed() must
                # raise ProtocolError rather than block waiting for more.
                bad.send_raw(b"$3\r\nabcXY")
                bad.expect_eof()
            finally:
                bad.close()
            self.assertTrue(srv.is_alive())

    def test_empty_array_command_closes_connection_without_crashing_server(self):
        # `*0\r\n` is well-formed RESP2 (a legal empty array), but C2
        # explicitly leaves execute()'s behavior on an empty command
        # array undefined and assigns the server the job of never
        # calling execute() with it. Without a guard, engine.py's
        # execute() does args[0].value on an empty list and raises an
        # uncaught IndexError.
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                bad.send_raw(b"*0\r\n")
                bad.expect_eof()
            finally:
                bad.close()

            self.assertTrue(srv.is_alive(), "server process crashed on empty Array command")

            good = srv.connect()
            try:
                good.send(b"PING")
                self.assertEqual(good.read_reply(), (b"+", "PONG"))
            finally:
                good.close()

    def test_nil_array_command_closes_connection_without_crashing_server(self):
        # `*-1\r\n` is the well-formed RESP nil array (Array(None)).
        # command.value would be None; args[0] on None raises TypeError.
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                bad.send_raw(b"*-1\r\n")
                bad.expect_eof()
            finally:
                bad.close()
            self.assertTrue(srv.is_alive())

    def test_non_bulkstring_array_element_closes_connection(self):
        # A well-formed Array whose element is an Integer, not a
        # BulkString — legal RESP2, but not a shape execute() is
        # contracted to accept.
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                bad.send_raw(b"*1\r\n:5\r\n")
                bad.expect_eof()
            finally:
                bad.close()
            self.assertTrue(srv.is_alive())

    def test_non_array_top_level_frame_closes_connection(self):
        # A well-formed top-level frame that isn't an Array at all (a
        # client sending a bare SimpleString instead of a command
        # array). Not malformed RESP, just not a command shape.
        with ServerProcess() as srv:
            bad = srv.connect()
            try:
                bad.send_raw(b"+PING\r\n")
                bad.expect_eof()
            finally:
                bad.close()
            self.assertTrue(srv.is_alive())

            good = srv.connect()
            try:
                good.send(b"PING")
                self.assertEqual(good.read_reply(), (b"+", "PONG"))
            finally:
                good.close()

    def test_client_disconnect_with_zero_bytes_does_not_crash_server(self):
        # Connect and immediately disconnect without sending anything.
        with ServerProcess() as srv:
            c = srv.connect()
            c.close()
            time.sleep(0.2)
            self.assertTrue(srv.is_alive(), "server crashed on immediate zero-byte disconnect")

            good = srv.connect()
            try:
                good.send(b"PING")
                self.assertEqual(good.read_reply(), (b"+", "PONG"))
            finally:
                good.close()

    def test_partial_frame_then_disconnect_does_not_crash_server(self):
        # Half a frame, then the client goes away before completing it.
        # No ProtocolError (it's a valid prefix, not malformed) — the
        # server must just see EOF and clean up.
        with ServerProcess() as srv:
            c = srv.connect()
            c.send_raw(b"*2\r\n$3\r\n")  # incomplete: array header + partial bulk string
            c.close()
            time.sleep(0.2)
            self.assertTrue(srv.is_alive(), "server crashed on partial frame + disconnect")

            good = srv.connect()
            try:
                good.send(b"PING")
                self.assertEqual(good.read_reply(), (b"+", "PONG"))
            finally:
                good.close()


class TestSharedEngineState(unittest.TestCase):
    def test_state_set_on_one_connection_visible_from_another(self):
        with ServerProcess() as srv:
            c1 = srv.connect()
            try:
                c1.send(b"SET", b"shared", b"hello")
                self.assertEqual(c1.read_reply(), (b"+", "OK"))
            finally:
                c1.close()

            # Separate, later connection — must see the same Engine's
            # state (one Engine for the server's lifetime, not one per
            # connection).
            c2 = srv.connect()
            try:
                c2.send(b"GET", b"shared")
                self.assertEqual(c2.read_reply(), (b"$", b"hello"))
            finally:
                c2.close()

    def test_incr_state_accumulates_across_connections(self):
        with ServerProcess() as srv:
            c1 = srv.connect()
            try:
                c1.send(b"INCR", b"counter")
                self.assertEqual(c1.read_reply(), (b":", 1))
            finally:
                c1.close()

            c2 = srv.connect()
            try:
                c2.send(b"INCR", b"counter")
                self.assertEqual(c2.read_reply(), (b":", 2))
            finally:
                c2.close()


class TestCliPortContract(unittest.TestCase):
    def test_dashdash_port_flag(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        proc = subprocess.Popen(
            [sys.executable, _SERVER_PY, "--port", str(port)],
            cwd=_TARGET_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self._wait_and_ping(proc, port)
        finally:
            self._terminate(proc)

    def test_port_env_var(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        env = dict(os.environ)
        env["PORT"] = str(port)
        proc = subprocess.Popen(
            [sys.executable, _SERVER_PY],
            cwd=_TARGET_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self._wait_and_ping(proc, port)
        finally:
            self._terminate(proc)

    def _terminate(self, proc) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

    def _wait_and_ping(self, proc, port, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate()
                self.fail(f"server exited early: stdout={out!r} stderr={err!r}")
            try:
                c = RespConn(port, timeout=0.5)
                break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail(f"server did not become ready on port {port}")
        try:
            c.send(b"PING")
            self.assertEqual(c.read_reply(), (b"+", "PONG"))
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
