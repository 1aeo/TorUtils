#!/usr/bin/env python3
"""Minimal tor control-port client for the 41339 functional tests.

usage: ctl.py <port> <cookie-file> CMD [CMD...]
CMDs are sent in order.  Special CMDs:
  wait-hsdesc[:N]  wait up to N (default 15) s for HS_DESC RECEIVED/FAILED
  sleep:N          print async events for N seconds
Async (650) events are printed as they arrive.
"""
import binascii
import socket
import sys
import time

port, cookie = int(sys.argv[1]), sys.argv[2]
s = socket.create_connection(("127.0.0.1", port))
buf = b""


def readline(deadline=None):
    """Return one line, or None if the deadline passes first."""
    global buf
    while b"\r\n" not in buf:
        if deadline is not None:
            left = deadline - time.time()
            if left <= 0:
                return None
            s.settimeout(left)
        else:
            s.settimeout(None)
        try:
            data = s.recv(65536)
        except socket.timeout:
            return None
        if not data:
            raise SystemExit("control connection closed")
        buf += data
    line, buf = buf.split(b"\r\n", 1)
    return line.decode()


def cmd(c):
    s.sendall((c + "\r\n").encode())
    lines = []
    while True:
        line = readline()
        if line.startswith("650"):
            print(time.strftime("%H:%M:%S"), "EVENT", line, flush=True)
            continue
        lines.append(line)
        if line[3] == " ":
            break
    shown = c if not c.startswith("AUTHENTICATE") else "AUTHENTICATE <cookie>"
    print(time.strftime("%H:%M:%S"), ">", shown, "->", " | ".join(lines),
          flush=True)


with open(cookie, "rb") as cf:
    cmd("AUTHENTICATE " + binascii.hexlify(cf.read()).decode())
for c in sys.argv[3:]:
    if c.startswith("wait-hsdesc") or c.startswith("sleep:"):
        n = float(c.split(":")[1]) if ":" in c else 15.0
        deadline = time.time() + n
        while True:
            line = readline(deadline)
            if line is None:
                if c.startswith("wait-hsdesc"):
                    print(time.strftime("%H:%M:%S"),
                          "TIMEOUT: no HS_DESC RECEIVED/FAILED", flush=True)
                break
            print(time.strftime("%H:%M:%S"), "EVENT", line, flush=True)
            if c.startswith("wait-hsdesc") and (
                    "HS_DESC RECEIVED" in line or "HS_DESC FAILED" in line):
                break
    else:
        cmd(c)
