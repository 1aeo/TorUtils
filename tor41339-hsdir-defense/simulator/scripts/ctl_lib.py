#!/usr/bin/env python3
"""Minimal Tor control-port client library for the ticket 41339 closed-lab
HSDir-flood simulator.  Loopback only; talks to chutney nodes we own.

Adapted from evidence/prior-macos-chutney/ctl.py.
"""
import binascii
import socket
import time


class Ctl:
    def __init__(self, port, cookie_path, host="127.0.0.1", timeout=30.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        with open(cookie_path, "rb") as f:
            self.authenticate(f.read())

    def _readline(self, deadline=None):
        while b"\r\n" not in self.buf:
            if deadline is not None:
                left = deadline - time.time()
                if left <= 0:
                    return None
                self.s.settimeout(left)
            else:
                self.s.settimeout(None)
            try:
                data = self.s.recv(65536)
            except socket.timeout:
                return None
            if not data:
                raise SystemExit("control connection closed")
            self.buf += data
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line.decode(errors="replace")

    def cmd(self, c):
        """Send one command, return (ok, lines). Async 650 events are
        collected into self.pending_events."""
        if not hasattr(self, "pending_events"):
            self.pending_events = []
        self.s.sendall((c + "\r\n").encode())
        lines = []
        while True:
            line = self._readline()
            if line is None:
                break
            if line.startswith("650"):
                self.pending_events.append((time.time(), line))
                continue
            lines.append(line)
            if len(line) >= 4 and line[3] == " ":
                break
        ok = bool(lines) and lines[-1].startswith("250")
        return ok, lines

    def authenticate(self, cookie):
        return self.cmd("AUTHENTICATE " + binascii.hexlify(cookie).decode())

    def burst(self, cmds):
        """Pipeline a list of commands: send them all at once, then drain all
        the sync replies (collecting any 650 events into pending_events).
        Returns the number of '250'-prefixed reply lines seen."""
        if not hasattr(self, "pending_events"):
            self.pending_events = []
        payload = "".join(c + "\r\n" for c in cmds).encode()
        self.s.sendall(payload)
        replies = 0
        n = len(cmds)
        seen = 0
        while seen < n:
            line = self._readline(deadline=time.time() + 30)
            if line is None:
                break
            if line.startswith("650"):
                self.pending_events.append((time.time(), line))
                continue
            if len(line) >= 4 and line[3] == " ":
                seen += 1
                if line.startswith("250"):
                    replies += 1
        return replies

    def setevents(self, *events):
        return self.cmd("SETEVENTS " + " ".join(events))

    def collect_events(self, duration, match=None):
        """Read events for `duration` seconds; return list of (ts, line).
        If `match` is given, stop early when a line contains it."""
        out = []
        if hasattr(self, "pending_events"):
            out.extend(self.pending_events)
            self.pending_events = []
        deadline = time.time() + duration
        while True:
            line = self._readline(deadline)
            if line is None:
                break
            if line.startswith("650"):
                out.append((time.time(), line))
                if match is not None and match in line:
                    break
        return out

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass
