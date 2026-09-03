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

from codec import Array, BulkString, Error, Integer, ProtocolError, RespCodec, SimpleString, encode


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

    def test_binary_safe_bulk_string(self):
        """Binary-safe bulk string with embedded CRLF and NUL round-trips."""
        # Create a bulk string containing \r, \n, and \x00
        payload = b"hello\r\nworld\x00test"
        frame = BulkString(payload)

        # Encode to wire format
        wire = encode(frame)

        # Feed into a fresh codec
        codec = RespCodec()
        frames = codec.feed(wire)

        # Verify it round-trips exactly
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], frame)
        self.assertEqual(frames[0].value, payload)

    def test_multiple_frames_one_feed_call(self):
        """Two complete frames arriving in one feed() call both surface, in order."""
        codec = RespCodec()

        # Create two frames: a simple PING array and a PONG simple string
        frame1 = Array([BulkString(b"PING")])
        frame2 = SimpleString("PONG")

        # Encode both to wire format and concatenate
        wire = encode(frame1) + encode(frame2)

        # Feed both at once
        frames = codec.feed(wire)

        # Verify both frames appear in order
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0], frame1)
        self.assertEqual(frames[1], frame2)

    def test_null_bulk_and_array(self):
        """Null bulk string ($-1) and null array (*-1) round-trip."""
        # Test null bulk string
        null_bulk = BulkString(None)
        wire_bulk = encode(null_bulk)
        codec_bulk = RespCodec()
        frames_bulk = codec_bulk.feed(wire_bulk)
        self.assertEqual(frames_bulk, [null_bulk])

        # Test null array
        null_array = Array(None)
        wire_array = encode(null_array)
        codec_array = RespCodec()
        frames_array = codec_array.feed(wire_array)
        self.assertEqual(frames_array, [null_array])

    def test_negative_length_raises(self):
        """Negative bulk/array length other than -1 raises ProtocolError."""
        codec = RespCodec()

        # Negative bulk string length other than -1
        with self.assertRaises(ProtocolError):
            codec.feed(b"$-2\r\n")

        # Negative array length other than -1
        codec = RespCodec()
        with self.assertRaises(ProtocolError):
            codec.feed(b"*-2\r\n")

    def test_integer_and_error_round_trip(self):
        """Integer and Error frame types round-trip."""
        # Test Integer frame
        int_frame = Integer(42)
        wire_int = encode(int_frame)
        codec_int = RespCodec()
        frames_int = codec_int.feed(wire_int)
        self.assertEqual(frames_int, [int_frame])
        self.assertEqual(frames_int[0].value, 42)

        # Test Error frame
        error_frame = Error("ERR unknown command")
        wire_error = encode(error_frame)
        codec_error = RespCodec()
        frames_error = codec_error.feed(wire_error)
        self.assertEqual(frames_error, [error_frame])
        self.assertEqual(frames_error[0].value, "ERR unknown command")


if __name__ == "__main__":
    unittest.main()
