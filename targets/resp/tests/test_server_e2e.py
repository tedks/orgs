"""End-to-end tests for server socket lifecycle.

Tests the server's ability to handle pipelining, connection teardown,
and malformed input per the acceptance criteria in work-packages/wp-server.md.

Uses raw sockets to exercise pipelining (which redis-cli cannot) and
connection teardown scenarios.

Run: python3 -m unittest targets.resp.tests.test_server_e2e -v
  (or, from targets/resp/: python3 -m unittest tests.test_server_e2e -v)
"""
import os
import socket
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codec import Array, BulkString, SimpleString, encode


def find_free_port():
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerE2ETestCase(unittest.TestCase):
    """Base class for server e2e tests. Manages server lifecycle."""

    @classmethod
    def setUpClass(cls):
        """Start server once per test class."""
        cls.port = find_free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, "targets/resp/server.py", "--port", str(cls.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Give server time to bind
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        """Stop server after all tests."""
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait()

    def connect(self):
        """Create a connected socket to the server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))
        return sock


class BasicPingTests(ServerE2ETestCase):
    """Basic sanity checks that the server works at all."""

    def test_single_ping(self):
        """A single PING command should receive PONG."""
        with self.connect() as sock:
            # Send: PING
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            # Read response: +PONG\r\n
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_ping_with_message(self):
        """PING with a message should echo the message as a bulk string."""
        with self.connect() as sock:
            # Send: PING "hello"
            sock.sendall(b"*2\r\n$4\r\nPING\r\n$5\r\nhello\r\n")
            # Read response: $5\r\nhello\r\n
            response = sock.recv(1024)
            self.assertEqual(response, b"$5\r\nhello\r\n")


class PipeliningTests(ServerE2ETestCase):
    """Test that the server correctly handles pipelined requests.

    Pipelining means multiple requests written to the socket before
    either response is read. This is the key test that redis-cli cannot
    exercise (redis-cli sends line-by-line and reads responses sequentially).
    """

    def test_pipelined_ping_ping(self):
        """Two PING commands sent together should both receive PONG."""
        with self.connect() as sock:
            # Send two PING commands without reading responses
            sock.sendall(b"*1\r\n$4\r\nPING\r\n*1\r\n$4\r\nPING\r\n")

            # Read first response
            first_response = sock.recv(1024)
            # Read second response (may arrive in same packet or separate)
            if len(first_response) < 14:  # +PONG\r\n is 7 bytes, need 14 for two
                second_response = sock.recv(1024)
                responses = first_response + second_response
            else:
                responses = first_response

            # Both responses should be +PONG\r\n
            self.assertEqual(responses, b"+PONG\r\n+PONG\r\n")

    def test_pipelined_ping_with_message(self):
        """Two different PING commands should be answered in order."""
        with self.connect() as sock:
            # Send: PING "one" followed by PING "two"
            msg1 = b"*2\r\n$4\r\nPING\r\n$3\r\none\r\n"
            msg2 = b"*2\r\n$4\r\nPING\r\n$3\r\ntwo\r\n"
            sock.sendall(msg1 + msg2)

            # Read responses
            response1 = sock.recv(1024)
            if b"two" not in response1:
                response2 = sock.recv(1024)
                response1 += response2

            # First should be $3\r\none\r\n, second should be $3\r\ntwo\r\n
            self.assertIn(b"$3\r\none\r\n", response1)
            self.assertIn(b"$3\r\ntwo\r\n", response1)
            # Verify order
            self.assertLess(response1.find(b"one"), response1.find(b"two"))

    def test_three_pipelined_requests(self):
        """Three or more pipelined requests should work."""
        with self.connect() as sock:
            # Send three PING commands
            sock.sendall(b"*1\r\n$4\r\nPING\r\n" * 3)

            # Read all responses
            all_responses = b""
            while all_responses.count(b"+PONG\r\n") < 3:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                all_responses += chunk

            # Should have three PONGs
            self.assertEqual(all_responses.count(b"+PONG\r\n"), 3)


class ConnectionTeardownTests(ServerE2ETestCase):
    """Test that server handles connection teardown gracefully."""

    def test_close_after_complete_request(self):
        """Connection closed after a complete request should not crash server."""
        # First connection
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

        # Connection closed; should be able to open a new one
        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_close_with_incomplete_frame(self):
        """Connection closed mid-frame should not crash server."""
        # Send partial frame and close
        sock = self.connect()
        sock.sendall(b"*1\r\n$4\r\nP")  # Incomplete: "PING" not complete
        sock.close()

        # Server should still accept new connections
        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_close_with_partial_command_frame(self):
        """Connection closed with a partial command array should not crash."""
        sock = self.connect()
        sock.sendall(b"*2\r\n$4\r\nPING\r\n")  # Incomplete: missing second element
        sock.close()

        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_immediate_close(self):
        """Connecting then immediately closing should not crash server."""
        sock = self.connect()
        sock.close()

        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")


class MalformedInputTests(ServerE2ETestCase):
    """Test that server handles malformed RESP gracefully."""

    def test_invalid_type_byte(self):
        """Invalid type byte should close connection without crashing server."""
        sock = self.connect()
        sock.sendall(b"?invalid\r\n")
        # Connection should close (server closes it after ProtocolError)
        response = sock.recv(1024)
        self.assertEqual(response, b"")  # Empty means connection closed
        sock.close()

        # Server should still accept new connections
        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_malformed_array_length(self):
        """Invalid array length should close connection."""
        sock = self.connect()
        sock.sendall(b"*abc\r\ngarbage\r\n")
        response = sock.recv(1024)
        self.assertEqual(response, b"")  # Connection closed
        sock.close()

        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_malformed_bulk_length(self):
        """Invalid bulk string length should close connection."""
        sock = self.connect()
        sock.sendall(b"*1\r\n$notanumber\r\nPING\r\n")
        response = sock.recv(1024)
        self.assertEqual(response, b"")  # Connection closed
        sock.close()

        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")

    def test_bulk_string_missing_crlf(self):
        """Bulk string not terminated by CRLF should close connection."""
        sock = self.connect()
        sock.sendall(b"*1\r\n$4\r\nPINGXX\r\n")  # "PING" is only 4 bytes, but we send 6
        response = sock.recv(1024)
        self.assertEqual(response, b"")  # Connection closed
        sock.close()

        time.sleep(0.1)
        with self.connect() as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(1024)
            self.assertEqual(response, b"+PONG\r\n")


if __name__ == "__main__":
    unittest.main()
