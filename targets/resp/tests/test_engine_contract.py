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

from codec import BulkString, Error, Integer, SimpleString
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

    def test_echo(self):
        """ECHO happy path + wrong arity error"""
        engine = Engine()
        # Happy path: exactly 1 arg
        result = engine.execute([b"ECHO", b"hello"])
        self.assertEqual(result, BulkString(b"hello"))

        # Case insensitive
        result = engine.execute([b"echo", b"world"])
        self.assertEqual(result, BulkString(b"world"))

        # Wrong arity: no args (just command name)
        result = engine.execute([b"ECHO"])
        self.assertIsInstance(result, Error)
        self.assertIn("wrong number", result.value.lower())

        # Wrong arity: too many args
        result = engine.execute([b"ECHO", b"hello", b"world"])
        self.assertIsInstance(result, Error)
        self.assertIn("wrong number", result.value.lower())

    def test_set_get(self):
        """SET then GET round-trips the value; GET on missing key returns nil BulkString(None)"""
        engine = Engine()

        # SET and GET
        set_result = engine.execute([b"SET", b"mykey", b"myvalue"])
        self.assertEqual(set_result, SimpleString("OK"))

        get_result = engine.execute([b"GET", b"mykey"])
        self.assertEqual(get_result, BulkString(b"myvalue"))

        # GET on missing key returns nil
        get_missing = engine.execute([b"GET", b"nonexistent"])
        self.assertEqual(get_missing, BulkString(None))

    def test_del(self):
        """DEL returns 1 for an existing key, 0 for a missing key"""
        engine = Engine()

        # Set a key first
        engine.execute([b"SET", b"key1", b"value1"])

        # DEL existing key returns 1
        result = engine.execute([b"DEL", b"key1"])
        self.assertEqual(result, Integer(1))

        # DEL on missing key returns 0
        result = engine.execute([b"DEL", b"nonexistent"])
        self.assertEqual(result, Integer(0))

        # DEL again on already-deleted key returns 0
        result = engine.execute([b"DEL", b"key1"])
        self.assertEqual(result, Integer(0))

    def test_incr(self):
        """SET n 10 then INCR n returns Integer(11); INCR on absent key starts from 0"""
        engine = Engine()

        # SET a numeric value
        engine.execute([b"SET", b"counter", b"10"])

        # INCR existing key
        result = engine.execute([b"INCR", b"counter"])
        self.assertEqual(result, Integer(11))

        # Verify the value was updated
        get_result = engine.execute([b"GET", b"counter"])
        self.assertEqual(get_result, BulkString(b"11"))

        # INCR on absent key (should start from 0)
        result = engine.execute([b"INCR", b"newcounter"])
        self.assertEqual(result, Integer(1))

        # Verify it was stored as "1"
        get_result = engine.execute([b"GET", b"newcounter"])
        self.assertEqual(get_result, BulkString(b"1"))

    def test_incr_non_integer_errors(self):
        """INCR on a non-integer stored value returns an Error containing 'not an integer'"""
        engine = Engine()

        # SET a non-integer value
        engine.execute([b"SET", b"notint", b"hello"])

        # INCR on non-integer should error
        result = engine.execute([b"INCR", b"notint"])
        self.assertIsInstance(result, Error)
        self.assertIn("not an integer", result.value.lower())

        # Also test with empty string
        engine.execute([b"SET", b"empty", b""])
        result = engine.execute([b"INCR", b"empty"])
        self.assertIsInstance(result, Error)
        self.assertIn("not an integer", result.value.lower())

    def test_set_wrong_arity_errors(self):
        """SET with wrong arity (0, 1, or 3+ args) returns an Error containing 'wrong number'"""
        engine = Engine()

        # SET with no args (just command name)
        result = engine.execute([b"SET"])
        self.assertIsInstance(result, Error)
        self.assertIn("wrong number", result.value.lower())

        # SET with 1 arg (only key, no value)
        result = engine.execute([b"SET", b"key"])
        self.assertIsInstance(result, Error)
        self.assertIn("wrong number", result.value.lower())

        # SET with 3+ args (key, value, and extra args)
        result = engine.execute([b"SET", b"key", b"value", b"extra"])
        self.assertIsInstance(result, Error)
        self.assertIn("wrong number", result.value.lower())

    def test_binary_safe_value(self):
        """SET stores and GET returns binary-safe bytes (embedded CRLF, NUL)"""
        engine = Engine()

        # Value with embedded CRLF and NUL
        binary_value = b"hello\r\nworld\x00binary"

        # SET the binary value
        set_result = engine.execute([b"SET", b"binary_key", binary_value])
        self.assertEqual(set_result, SimpleString("OK"))

        # GET should return the exact same bytes
        get_result = engine.execute([b"GET", b"binary_key"])
        self.assertEqual(get_result, BulkString(binary_value))

        # Verify the value is not corrupted
        self.assertEqual(get_result.value, binary_value)

    def test_state_visibility_across_calls(self):
        """SET then GET on the same Engine instance is read-your-writes across calls"""
        engine = Engine()

        # First SET
        engine.execute([b"SET", b"key1", b"value1"])

        # First GET should see the SET
        result = engine.execute([b"GET", b"key1"])
        self.assertEqual(result, BulkString(b"value1"))

        # Update the value
        engine.execute([b"SET", b"key1", b"newvalue"])

        # GET should see the updated value
        result = engine.execute([b"GET", b"key1"])
        self.assertEqual(result, BulkString(b"newvalue"))

        # Multiple keys
        engine.execute([b"SET", b"key2", b"value2"])
        engine.execute([b"SET", b"key3", b"value3"])

        # All should be visible
        self.assertEqual(engine.execute([b"GET", b"key1"]), BulkString(b"newvalue"))
        self.assertEqual(engine.execute([b"GET", b"key2"]), BulkString(b"value2"))
        self.assertEqual(engine.execute([b"GET", b"key3"]), BulkString(b"value3"))


if __name__ == "__main__":
    unittest.main()
