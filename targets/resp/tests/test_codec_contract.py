"""Boundary tests for contract C1 (resp-codec), written by consumer `server`.
Skeleton committed at M1 (lead); wp-codec fills in the TODOs per the
acceptance criteria in work-packages/wp-codec.md. Stdlib only — no pytest.

Run: python3 -m unittest targets.resp.tests.test_codec_contract -v
  (or, from targets/resp/: python3 -m unittest tests.test_codec_contract -v)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codec import Array, BulkString, Integer, ProtocolError, RespCodec, SimpleString, encode


class RoundTripTests(unittest.TestCase):
    def test_ping_array_round_trips(self):
        codec = RespCodec()
        wire = b"*1\r\n$4\r\nPING\r\n"
        frames = codec.feed(wire)
        self.assertEqual(frames, [Array([BulkString(b"PING")])])
        self.assertEqual(encode(frames[0]), wire)

    def test_simple_string_encode(self):
        self.assertEqual(encode(SimpleString("PONG")), b"+PONG\r\n")

    def test_partial_feed_reassembles(self):
        codec = RespCodec()
        wire = b"*1\r\n$4\r\nPING\r\n"
        self.assertEqual(codec.feed(wire[:5]), [])
        frames = codec.feed(wire[5:])
        self.assertEqual(frames, [Array([BulkString(b"PING")])])

    def test_malformed_input_raises_protocol_error(self):
        codec = RespCodec()
        with self.assertRaises(ProtocolError):
            codec.feed(b"?not-a-type-byte\r\n")


class TodoTests(unittest.TestCase):
    """wp-codec: demonstrate each item against the running RespCodec/encode."""

    @unittest.skip("TODO(wp-codec): binary-safe bulk string with embedded CRLF and NUL round-trips")
    def test_binary_safe_bulk_string(self):
        ...

    @unittest.skip("TODO(wp-codec): two complete frames arriving in one feed() call both surface, in order")
    def test_multiple_frames_one_feed_call(self):
        ...

    @unittest.skip("TODO(wp-codec): null bulk string ($-1) and null array (*-1) round-trip")
    def test_null_bulk_and_array(self):
        ...

    @unittest.skip("TODO(wp-codec): negative bulk/array length other than -1 raises ProtocolError")
    def test_negative_length_raises(self):
        ...

    @unittest.skip("TODO(wp-codec): Integer and Error frame types round-trip")
    def test_integer_and_error_round_trip(self):
        ...


if __name__ == "__main__":
    unittest.main()
