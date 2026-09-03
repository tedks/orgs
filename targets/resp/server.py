#!/usr/bin/env python3
"""server: socket lifecycle — accept, read -> codec -> engine -> codec -> write,
connection teardown. No parsing, no command knowledge; consumes both C1 and C2.

Tracer bullet (lead-built, M1): sequential accept loop, one connection at a
time (spec's concurrency-model decision). Proves redis-cli PING answers PONG
through all three entities. Malformed-input teardown beyond "close the
socket" and any further robustness is wp-server's work.

Entry point graded by bench/conformance/resp_conformance.sh:
    python3 targets/resp/server.py --port <port>
"""
import argparse
import os
import socket
import sys

from codec import Array, BulkString, Error, ProtocolError, RespCodec, encode
from engine import Engine


def serve_connection(conn: socket.socket, engine: Engine) -> None:
    codec = RespCodec()
    with conn:
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            try:
                frames = codec.feed(data)
            except ProtocolError:
                return  # connection-fatal per C1
            for frame in frames:
                if not isinstance(frame, Array) or frame.value is None:
                    continue
                items = frame.value
                if not all(isinstance(item, BulkString) and item.value is not None for item in items):
                    # A command array element that isn't a non-null bulk string
                    # (e.g. a nested Array, or an explicit null bulk string) has
                    # no well-defined argument position to drop into — reject
                    # the whole command rather than silently reindexing the
                    # remaining arguments into a different, valid-looking arity.
                    conn.sendall(encode(Error("ERR protocol error: expected bulk string array")))
                    continue
                command = [item.value for item in items]
                reply = engine.execute(command)
                conn.sendall(encode(reply))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "6379")))
    args = parser.parse_args(argv)

    engine = Engine()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", args.port))
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            serve_connection(conn, engine)


if __name__ == "__main__":
    sys.exit(main())
