"""Supplementary unit tests for resp-codec — implementer's own scope per
work-packages/resp-codec.md ("You may add your own additional unit tests
... for anything the boundary tests don't cover"). Not the graded gate
(that's test_codec_boundary.py, frozen); this file covers cases the
boundary tests don't exercise, plus documents a known bug in the frozen
suite (see TestKnownBoundaryTestBug below).

Run: python3 -m unittest discover -s targets/resp/tests -p 'test_codec_impl.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import codec  # noqa: E402


class TestNestedAndMixedArrays(unittest.TestCase):
    def test_nested_array(self):
        p = codec.Parser()
        wire = b"*1\r\n*2\r\n:1\r\n+ok\r\n"
        got = p.feed(wire)
        self.assertEqual(
            got,
            [codec.Array([codec.Array([codec.Integer(1), codec.SimpleString("ok")])])],
        )

    def test_mixed_type_array(self):
        # Contract: parser must recognize all five types generally, not
        # just BulkString elements inside a top-level Array.
        p = codec.Parser()
        wire = b"*3\r\n:5\r\n+hi\r\n-oops\r\n"
        got = p.feed(wire)
        self.assertEqual(
            got,
            [codec.Array([codec.Integer(5), codec.SimpleString("hi"), codec.Error("oops")])],
        )

    def test_nested_array_split_byte_at_a_time(self):
        p = codec.Parser()
        whole = b"*1\r\n*1\r\n$3\r\nfoo\r\n"
        frames = []
        for i in range(len(whole)):
            frames.extend(p.feed(whole[i : i + 1]))
        self.assertEqual(
            frames, [codec.Array([codec.Array([codec.BulkString(b"foo")])])]
        )


class TestMalformedExtra(unittest.TestCase):
    def test_bulk_string_wrong_terminator_raises(self):
        # Declared length matches payload length, but the two bytes after
        # the payload aren't CRLF -> the payload/length boundary is bad.
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"$3\r\nabcXX")

    def test_array_element_malformed_propagates(self):
        p = codec.Parser()
        with self.assertRaises(codec.ProtocolError):
            p.feed(b"*1\r\n!bad\r\n")

    def test_empty_feed_on_fresh_parser_is_noop(self):
        p = codec.Parser()
        self.assertEqual(p.feed(b""), [])


class TestEncodeIsPure(unittest.TestCase):
    def test_encode_does_not_mutate_input_or_have_side_effects(self):
        frame = codec.Array([codec.BulkString(b"x")])
        before = codec.encode(frame)
        after = codec.encode(frame)
        self.assertEqual(before, after)
        self.assertEqual(frame.value, [codec.BulkString(b"x")])


class TestKnownBoundaryTestBug(unittest.TestCase):
    """Documents a bug found in the frozen test_codec_boundary.py, filed
    as a docs-bug rather than edited (boundary tests are frozen/owned by
    the lead). See status/resp-codec.md and
    events/resp-tracer/worker-codec.md for the deviation log entry.

    TestEncode.test_bulk_string_binary_safe and
    TestFeedBasic.test_feed_bulk_string_binary_safe both hardcode a `$7`
    length prefix for `payload = b"a\\r\\nb\\x00c"`, which is 6 bytes, not
    7 (verified: len(b"a\\r\\nb\\x00c") == 6). Per the C1 wire-format table,
    a BulkString's declared length must be exactly len(.value) ("Length is
    a byte count, not a text length") -- a correct codec must reject the
    mismatch, not paper over it, since C1's failure semantics explicitly
    list "a length that doesn't match the delivered payload boundary" as
    ProtocolError-worthy. This test proves the codec is correct for the
    same payload at its actual (correct) length, isolating the bug to the
    two literal `7`s in the frozen file rather than to this
    implementation.
    """

    def test_binary_safe_payload_round_trips_at_its_true_length(self):
        payload = b"a\r\nb\x00c"
        self.assertEqual(len(payload), 6)
        self.assertEqual(
            codec.encode(codec.BulkString(payload)),
            b"$6\r\n" + payload + b"\r\n",
        )
        p = codec.Parser()
        self.assertEqual(p.feed(b"$6\r\n" + payload + b"\r\n"), [codec.BulkString(payload)])

    def test_the_frozen_tests_literal_seven_byte_stream_is_actually_invalid(self):
        # This is exactly the byte stream TestFeedBasic
        # .test_feed_bulk_string_binary_safe feeds in. With a *correct*
        # length of 7, it declares 7 payload bytes, so the codec reads
        # buf[4:11] ("a\r\nb\x00c\r") as payload and then requires buf[11:13]
        # to be CRLF -- but the stream is only 12 bytes long, so no
        # terminator is available and the frame never completes.
        p = codec.Parser()
        payload = b"a\r\nb\x00c"
        wire = b"$7\r\n" + payload + b"\r\n"
        self.assertEqual(len(wire), 12)
        self.assertEqual(p.feed(wire), [])  # incomplete, not a parse of `payload`


if __name__ == "__main__":
    unittest.main()
