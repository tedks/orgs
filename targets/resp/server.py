"""server — socket lifecycle: accept, read -> codec -> engine -> codec -> write.

Hardened by the server work package to the full behavior in
docs/specs/2026-09-02-resp-tracer.md (Decisions: sequential accept loop,
one connection served at a time — no threading/async). Per connection:
read in a loop (recv() may return any chunk size, not "one command"),
feed bytes to a per-connection codec.Parser, execute() each completed
frame against the one engine.Engine instance shared for the server's
whole lifetime, encode() and write each reply, and keep serving that
connection across multiple sequential/pipelined commands until the
client disconnects or the input can't be safely handed to the engine.

No RESP parsing or command knowledge of its own — everything about bytes
goes through codec, everything about command semantics goes through
engine.
"""

import argparse
import os
import socket

import codec
import engine


def _is_command(frame) -> bool:
    """True iff `frame` is a shape engine.Engine.execute() is contracted
    to accept: an Array (not the RESP nil array) of one or more
    BulkString elements (contracts/C2-command-engine.md, Inputs/outputs).

    C2 explicitly leaves execute()'s behavior undefined for anything else
    (empty Array, nil Array, non-BulkString elements) and assigns the
    precondition to the caller: "the server is responsible for only
    calling execute() with such input." Skipping this check is not
    theoretical — engine.py's execute() does `args[0].value` on the raw
    Array contents with no length/type guard, so an empty or nil Array
    raises an uncaught IndexError/TypeError that would otherwise escape
    the per-connection loop.
    """
    return (
        isinstance(frame, codec.Array)
        and frame.value is not None
        and len(frame.value) > 0
        and all(isinstance(element, codec.BulkString) for element in frame.value)
    )


def _handle_connection(conn: socket.socket, eng: "engine.Engine") -> None:
    """Serve one connection to completion: read -> codec -> engine ->
    codec -> write, repeated for as many sequential/pipelined commands as
    the client sends, until it disconnects or this connection must be
    torn down. Never lets an exception escape — the caller (the accept
    loop) must keep running regardless of what this connection does.
    """
    parser = codec.Parser()
    try:
        while True:
            data = conn.recv(65536)
            if data == b"":
                # Orderly client-side shutdown (recv() EOF), including a
                # client that connects and disconnects without sending
                # anything at all. Nothing left to do for this connection.
                return

            try:
                frames = parser.feed(data)
            except codec.ProtocolError:
                # Connection-fatal per C1: the parser's post-error state
                # is unspecified, so feed() must never be called again on
                # it. Close this connection only; the server keeps running.
                return

            for frame in frames:
                if not _is_command(frame):
                    # Well-formed RESP2 that doesn't shape into something
                    # execute() is contracted to accept. Treat the same
                    # as a malformed frame: fatal to this connection, not
                    # to the server.
                    return
                reply = eng.execute(frame)
                conn.sendall(codec.encode(reply))
    except OSError:
        # The client reset/aborted the connection out from under us
        # (e.g. ECONNRESET on recv(), a broken pipe on sendall()). Not a
        # server-process problem — this connection is simply done.
        return


def serve(port: int) -> None:
    eng = engine.Engine()  # one engine instance for the server's lifetime —
    # state must be visible across connections (real Redis persists data
    # across client reconnects), never re-created per connection.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        while True:
            conn, _ = srv.accept()
            with conn:
                _handle_connection(conn, eng)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 6379)))
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
