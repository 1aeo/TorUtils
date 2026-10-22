#!/usr/bin/env python3
"""Tiny loopback HTTP server for the private client-reachability lab.

Every onion service in the clientlab41339 net forwards its virtual port to
127.0.0.1:<PORT> (chutney's shared hidden-service target port, default 4747).
This server binds that port and returns a short fixed body for any path, so a
client that reaches any onion over the private net gets a real HTTP 200. It is
loopback only and serves no files from disk.

usage: httpd.py [PORT]   (default 4747)
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BODY = b"clientlab41339 onion reachable\n"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass  # quiet


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4747
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print("httpd on 127.0.0.1:%d" % port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
