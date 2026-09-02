"""Boundary tests for C2 (contracts/C2-command-engine.md) — pre-written by
the lead at decomposition, consumer-driven (what `server` needs from
`engine`). The command-engine work package must make these pass without
editing them; edits here are a spec/contract amendment, not implementation
work.

Depends only on C1's Frame *types* (SimpleString/Error/Integer/BulkString/
Array), never on codec.Parser/encode, matching C2's declared dependency.

Run: python3 -m unittest discover -s targets/resp/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import engine  # noqa: E402
from codec import Array, BulkString, Error, Integer, SimpleString  # noqa: E402


def cmd(*args):
    """Build an Array[BulkString] command frame from str/bytes args."""
    return Array([BulkString(a.encode() if isinstance(a, str) else a) for a in args])


class TestPing(unittest.TestCase):
    def test_no_arg(self):
        self.assertEqual(engine.Engine().execute(cmd("PING")), SimpleString("PONG"))

    def test_case_insensitive_dispatch(self):
        self.assertEqual(engine.Engine().execute(cmd("ping")), SimpleString("PONG"))
        self.assertEqual(engine.Engine().execute(cmd("PiNg")), SimpleString("PONG"))

    def test_one_arg_echoes(self):
        self.assertEqual(engine.Engine().execute(cmd("PING", "hi")), BulkString(b"hi"))

    def test_wrong_arity(self):
        r = engine.Engine().execute(cmd("PING", "a", "b"))
        self.assertIsInstance(r, Error)


class TestEcho(unittest.TestCase):
    def test_echo(self):
        self.assertEqual(engine.Engine().execute(cmd("ECHO", "hello")), BulkString(b"hello"))

    def test_wrong_arity_zero(self):
        self.assertIsInstance(engine.Engine().execute(cmd("ECHO")), Error)

    def test_wrong_arity_two(self):
        self.assertIsInstance(engine.Engine().execute(cmd("ECHO", "a", "b")), Error)


class TestGetSet(unittest.TestCase):
    def test_set_then_get(self):
        e = engine.Engine()
        self.assertEqual(e.execute(cmd("SET", "k", "v")), SimpleString("OK"))
        self.assertEqual(e.execute(cmd("GET", "k")), BulkString(b"v"))

    def test_get_missing_is_nil(self):
        e = engine.Engine()
        self.assertEqual(e.execute(cmd("GET", "nope")), BulkString(None))

    def test_set_binary_safe_value(self):
        e = engine.Engine()
        payload = b"a\r\nb\x00c"
        e.execute(Array([BulkString(b"SET"), BulkString(b"bin"), BulkString(payload)]))
        self.assertEqual(e.execute(cmd("GET", "bin")), BulkString(payload))

    def test_set_wrong_arity(self):
        self.assertIsInstance(engine.Engine().execute(cmd("SET", "onlykey")), Error)
        self.assertIsInstance(engine.Engine().execute(cmd("SET", "k", "v", "extra")), Error)

    def test_get_wrong_arity(self):
        self.assertIsInstance(engine.Engine().execute(cmd("GET")), Error)
        self.assertIsInstance(engine.Engine().execute(cmd("GET", "a", "b")), Error)

    def test_set_overwrites(self):
        e = engine.Engine()
        e.execute(cmd("SET", "k", "v1"))
        e.execute(cmd("SET", "k", "v2"))
        self.assertEqual(e.execute(cmd("GET", "k")), BulkString(b"v2"))


class TestDel(unittest.TestCase):
    def test_del_present_key(self):
        e = engine.Engine()
        e.execute(cmd("SET", "k", "v"))
        self.assertEqual(e.execute(cmd("DEL", "k")), Integer(1))
        self.assertEqual(e.execute(cmd("GET", "k")), BulkString(None))

    def test_del_missing_key(self):
        self.assertEqual(engine.Engine().execute(cmd("DEL", "nope")), Integer(0))

    def test_del_variadic_mixed(self):
        e = engine.Engine()
        e.execute(cmd("SET", "a", "1"))
        e.execute(cmd("SET", "b", "2"))
        self.assertEqual(e.execute(cmd("DEL", "a", "b", "c")), Integer(2))

    def test_del_wrong_arity(self):
        self.assertIsInstance(engine.Engine().execute(cmd("DEL")), Error)


class TestIncr(unittest.TestCase):
    def test_incr_missing_key_starts_at_one(self):
        self.assertEqual(engine.Engine().execute(cmd("INCR", "n")), Integer(1))

    def test_incr_existing_integer(self):
        e = engine.Engine()
        e.execute(cmd("SET", "n", "10"))
        self.assertEqual(e.execute(cmd("INCR", "n")), Integer(11))

    def test_incr_twice_accumulates(self):
        e = engine.Engine()
        e.execute(cmd("INCR", "n"))
        self.assertEqual(e.execute(cmd("INCR", "n")), Integer(2))

    def test_incr_non_integer_value_errors_and_leaves_value(self):
        e = engine.Engine()
        e.execute(cmd("SET", "s", "abc"))
        r = e.execute(cmd("INCR", "s"))
        self.assertIsInstance(r, Error)
        self.assertEqual(e.execute(cmd("GET", "s")), BulkString(b"abc"))

    def test_incr_negative(self):
        e = engine.Engine()
        e.execute(cmd("SET", "n", "-3"))
        self.assertEqual(e.execute(cmd("INCR", "n")), Integer(-2))

    def test_incr_wrong_arity(self):
        self.assertIsInstance(engine.Engine().execute(cmd("INCR")), Error)
        self.assertIsInstance(engine.Engine().execute(cmd("INCR", "a", "b")), Error)


class TestUnknownCommand(unittest.TestCase):
    def test_unknown_command_is_error_not_exception(self):
        r = engine.Engine().execute(cmd("FROB", "x"))
        self.assertIsInstance(r, Error)


class TestStateVisibility(unittest.TestCase):
    def test_state_persists_across_calls_on_same_instance(self):
        e = engine.Engine()
        e.execute(cmd("SET", "k", "v"))
        e.execute(cmd("PING"))  # unrelated call in between
        self.assertEqual(e.execute(cmd("GET", "k")), BulkString(b"v"))

    def test_fresh_instance_has_no_state(self):
        e1 = engine.Engine()
        e1.execute(cmd("SET", "k", "v"))
        e2 = engine.Engine()
        self.assertEqual(e2.execute(cmd("GET", "k")), BulkString(None))


if __name__ == "__main__":
    unittest.main()
