# Malformed-wire corpus

Real clients (`redis-cli`) mostly exercise happy-path encoding, so a
dangerously permissive parser can pass the conformance exam while being
wrong. This corpus feeds raw bytes at the server's socket and asserts it
rejects or survives them without crashing, hanging, or mis-framing.

Each case is a file: `NN-description.in` holds the raw bytes to send, and
`NN-description.expect` describes the required handling (a reply prefix, or
`CLOSE` for a connection the server should drop, or `NOCRASH` for input it
must survive). Populated during the RESP sprint's hardening; the harness that
replays them lands with v1.

Planned cases (RESP2 subset): truncated bulk length, bulk length exceeding
declared size, negative multibulk count, non-numeric length header,
embedded NUL in inline command, oversized length (overflow), missing CRLF
terminator, unterminated array.
