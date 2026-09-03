"""Boundary tests for contract C2 (command-engine), written by consumer `server`.
Skeleton committed at M1 (lead); wp-engine fills in the TODOs per the
acceptance criteria in work-packages/wp-engine.md. Stdlib only — no pytest.

Run: python3 -m unittest targets.resp.tests.test_engine_contract -v
  (or, from targets/resp/: python3 -m unittest tests.test_engine_contract -v)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codec import BulkString, SimpleString
from engine import Engine


class PingTests(unittest.TestCase):
    def test_ping_no_arg(self):
        self.assertEqual(Engine().execute([b"PING"]), SimpleString("PONG"))

    def test_ping_case_insensitive(self):
        self.assertEqual(Engine().execute([b"ping"]), SimpleString("PONG"))

    def test_ping_with_message(self):
        self.assertEqual(Engine().execute([b"PING", b"hello"]), BulkString(b"hello"))


class TodoTests(unittest.TestCase):
    """wp-engine: demonstrate each item against a running Engine instance."""

    @unittest.skip("TODO(wp-engine): ECHO happy path + wrong arity error")
    def test_echo(self):
        ...

    @unittest.skip("TODO(wp-engine): SET then GET round-trips the value; GET on missing key returns nil BulkString(None)")
    def test_set_get(self):
        ...

    @unittest.skip("TODO(wp-engine): DEL returns 1 for an existing key, 0 for a missing key")
    def test_del(self):
        ...

    @unittest.skip("TODO(wp-engine): SET n 10 then INCR n returns Integer(11); INCR on absent key starts from 0")
    def test_incr(self):
        ...

    @unittest.skip("TODO(wp-engine): INCR on a non-integer stored value returns an Error containing 'not an integer'")
    def test_incr_non_integer_errors(self):
        ...

    @unittest.skip("TODO(wp-engine): SET with wrong arity (0, 1, or 3+ args) returns an Error containing 'wrong number'")
    def test_set_wrong_arity_errors(self):
        ...

    @unittest.skip("TODO(wp-engine): SET stores and GET returns binary-safe bytes (embedded CRLF, NUL)")
    def test_binary_safe_value(self):
        ...

    @unittest.skip("TODO(wp-engine): SET then GET on the same Engine instance is read-your-writes across calls")
    def test_state_visibility_across_calls(self):
        ...


if __name__ == "__main__":
    unittest.main()
