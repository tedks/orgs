"""server — socket lifecycle: accept, read -> codec -> engine -> codec -> write.

TRACER BULLET (M1): sequential accept loop, one connection at a time, one
command per connection (crude — no read-until-disconnect loop, no
pipelining support yet). Hardened by the server work package to the full
behavior in docs/specs/2026-09-02-resp-tracer.md (Decisions: sequential
accept loop, one connection at a time).
"""

import argparse
import os
import socket

import codec
import engine


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
                parser = codec.Parser()
                data = conn.recv(65536)
                for frame in parser.feed(data):
                    reply = eng.execute(frame)
                    conn.sendall(codec.encode(reply))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 6379)))
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
