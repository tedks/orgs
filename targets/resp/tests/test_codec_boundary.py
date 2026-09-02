"""Boundary tests for C1 (contracts/C1-resp-codec.md) — pre-written by the
lead at decomposition, consumer-driven (what `server` needs from `codec`).
The resp-codec work package must make these pass without editing them;
edits here are a spec/contract amendment, not implementation work.

Run: python3 -m unittest discover -s targets/resp/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import codec  # noqa: E402


class TestEncode(unittest.TestCase):
    def test_simple_string(self):
        self.assertEqual(codec.encode(codec.SimpleString("PONG")), b"+PONG\r\n")

    def test_error(self):
        self.assertEqual(codec.encode(codec.Error("ERR oops")), b"-ERR oops\r\n")

    def test_integer(self):
        self.assertEqual(codec.encode(codec.Integer(1000)), b":1000\r\n")

    def test_integer_negative(self):
        self.assertEqual(codec.encode(codec.Integer(-5)), b":-5\r\n")

    def test_bulk_string(self):
        self.assertEqual(codec.encode(codec.BulkString(b"foobar")), b"$6\r\nfoobar\r\n")

    def test_bulk_string_empty(self):
        self.assertEqual(codec.encode(codec.BulkString(b"")), b"$0\r\n\r\n")

    def test_bulk_string_nil(self):
        self.assertEqual(codec.encode(codec.BulkString(None)), b"$-1\r\n")

    def test_bulk_string_binary_safe(self):
        payload = b"a\r\nb\x00c"
        self.assertEqual(
            codec.encode(codec.BulkString(payload)),
            b"$7\r\n" + payload + b"\r\n",
        )

    def test_array(self):
        frame = codec.Array([codec.BulkString(b"PING")])
        self.assertEqual(codec.encode(frame), b"*1\r\n$4\r\nPING\r\n")

    def test_array_empty(self):
        self.assertEqual(codec.encode(codec.Array([])), b"*0\r\n")

    def test_array_nil(self):
        self.assertEqual(codec.encode(codec.Array(None)), b"*-1\r\n")


class TestFeedBasic(unittest.TestCase):
    def test_feed_simple_string(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"+OK\r\n"), [codec.SimpleString("OK")])

    def test_feed_error(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"-ERR bad\r\n"), [codec.Error("ERR bad")])

    def test_feed_integer(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b":42\r\n"), [codec.Integer(42)])

    def test_feed_integer_negative(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b":-7\r\n"), [codec.Integer(-7)])

    def test_feed_bulk_string(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"$6\r\nfoobar\r\n"), [codec.BulkString(b"foobar")])

    def test_feed_bulk_string_nil(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"$-1\r\n"), [codec.BulkString(None)])

    def test_feed_bulk_string_binary_safe(self):
        payload = b"a\r\nb\x00c"
        p = codec.Parser()
        self.assertEqual(
            p.feed(b"$7\r\n" + payload + b"\r\n"), [codec.BulkString(payload)]
        )

    def test_feed_array_of_bulkstrings(self):
        p = codec.Parser()
        got = p.feed(b"*2\r\n$3\r\nSET\r\n$1\r\nk\r\n")
        self.assertEqual(got, [codec.Array([codec.BulkString(b"SET"), codec.BulkString(b"k")])])

    def test_feed_array_nil(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"*-1\r\n"), [codec.Array(None)])

    def test_feed_array_empty(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"*0\r\n"), [codec.Array([])])


class TestFeedIncremental(unittest.TestCase):
    """The core C1 promise: chunk-boundary independence."""

    def test_split_across_two_calls(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"*1\r\n$4\r\nPI"), [])
        self.assertEqual(p.feed(b"NG\r\n"), [codec.Array([codec.BulkString(b"PING")])])

    def test_split_one_byte_at_a_time(self):
        p = codec.Parser()
        whole = b"*1\r\n$4\r\nPING\r\n"
        frames = []
        for i in range(len(whole)):
            frames.extend(p.feed(whole[i : i + 1]))
        self.assertEqual(frames, [codec.Array([codec.BulkString(b"PING")])])

    def test_two_frames_one_call(self):
        p = codec.Parser()
        got = p.feed(b"+PONG\r\n+PONG\r\n")
        self.assertEqual(got, [codec.SimpleString("PONG"), codec.SimpleString("PONG")])

    def test_two_pipelined_requests_one_call(self):
        p = codec.Parser()
        got = p.feed(b"*1\r\n$4\r\nPING\r\n*1\r\n$4\r\nPING\r\n")
        expect = codec.Array([codec.BulkString(b"PING")])
        self.assertEqual(got, [expect, expect])

    def test_remainder_retained_across_multiple_feeds(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b"+A\r\n+B"), [codec.SimpleString("A")])
        self.assertEqual(p.feed(b"\r\n+C\r\n"), [codec.SimpleString("B"), codec.SimpleString("C")])


class TestRoundTrip(unittest.TestCase):
    def test_round_trip_each_type(self):
        frames = [
            codec.SimpleString("OK"),
            codec.Error("ERR bad"),
            codec.Integer(123),
            codec.Integer(-1),
            codec.BulkString(b"hello"),
            codec.BulkString(b""),
            codec.BulkString(None),
            codec.BulkString(b"a\r\nb\x00c"),
            codec.Array([codec.BulkString(b"x"), codec.BulkString(b"y")]),
            codec.Array([]),
            codec.Array(None),
        ]
        for f in frames:
            with self.subTest(frame=f):
                p = codec.Parser()
                self.assertEqual(p.feed(codec.encode(f)), [f])


class TestMalformed(unittest.TestCase):
    def test_bad_type_sigil_raises(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"!not-a-type\r\n")

    def test_non_numeric_length_raises(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"$abc\r\nxxx\r\n")

    def test_non_numeric_integer_raises(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b":not-a-number\r\n")

    def test_array_negative_length_other_than_nil_raises(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"*-2\r\n")

    def test_bulk_string_negative_length_other_than_nil_raises(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"$-2\r\n")


if __name__ == "__main__":
    unittest.main()
