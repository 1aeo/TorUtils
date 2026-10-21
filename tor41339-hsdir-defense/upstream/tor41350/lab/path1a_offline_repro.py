#!/usr/bin/env python3
"""Offline reproduction of tor#41350 "Path 1a" (OR/received drift).

Run it ONLY inside a network namespace that has nothing but loopback, e.g.

    unshare -n sh -c 'ip link set lo up && python3 -I path1a_offline_repro.py /path/to/tor [--rst]'

It refuses to run if any non-loopback interface is up. It starts one relay
that cannot reach the Tor network, opens N real inbound TLS connections to its
ORPort, then stalls the relay (SIGSTOP) while M short-lived connections that
send non-TLS bytes or only a FIN (or, with --rst, an RST) wait in the accept
backlog (what a busy main
loop sees during a connection flood), resumes it, and compares
tor_relay_connections{type="OR",direction="received",state="opened"} with the
kernel's count of established ORPort sockets. Ports are chosen at run time.
"""
import http.client
import os
import re
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time

N_REAL, N_GARBAGE, N_FIN = 7, 5, 5


def only_loopback():
    out = subprocess.run(["ip", "-o", "link", "show", "up"],
                         capture_output=True, text=True).stdout
    names = [l.split(":")[1].strip() for l in out.splitlines() if ":" in l]
    return names == ["lo"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def metrics(port):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/metrics")
    body = c.getresponse().read().decode(errors="replace")
    c.close()
    return body


def or_received(text, state):
    name = "tor_relay_connections" + ("_total" if state == "created" else "")
    m = re.search(r'^%s\{type="OR",direction="received",state="%s",'
                  r'family="ipv4"\} (\d+)' % (name, state), text, re.M)
    return int(m.group(1)) if m else None


def listening(port):
    out = subprocess.run(["ss", "-Hltn", "( sport = :%d )" % port],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


def established(port):
    out = subprocess.run(["ss", "-Htn", "state", "established",
                          "( sport = :%d )" % port],
                         capture_output=True, text=True).stdout
    return len([l for l in out.splitlines() if l.strip()])


def main():
    rst = sys.argv[2:] == ["--rst"]
    if len(sys.argv) != 2 and not rst:
        sys.exit("usage: path1a_offline_repro.py TOR_BINARY [--rst]")
    if not only_loopback():
        sys.exit("refusing to run: a non-loopback interface is up "
                 "(use unshare -n and bring up lo only)")
    or_port, metrics_port = free_port(), free_port()
    datadir = tempfile.mkdtemp(prefix="tor41350-")
    torrc = os.path.join(datadir, "torrc")
    with open(torrc, "w") as f:
        f.write("DataDirectory %s\nORPort 127.0.0.1:%d\n"
                "MetricsPort 127.0.0.1:%d\nMetricsPortPolicy accept 127.0.0.1\n"
                "SocksPort 0\nAssumeReachable 1\nPublishServerDescriptor 0\n"
                "ExitRelay 0\nAddress 127.0.0.1\nLog err stderr\n"
                % (datadir, or_port, metrics_port))
    tor = subprocess.Popen([sys.argv[1], "-f", torrc],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def snapshot(title):
        text = metrics(metrics_port)
        print("%-38s gauge(opened)=%-3s created=%-3s kernel ESTAB=%d"
              % (title, or_received(text, "opened"),
                 or_received(text, "created"), established(or_port)))

    try:
        for _ in range(300):
            try:
                metrics(metrics_port)
                if listening(or_port):
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            sys.exit("tor did not start")
        time.sleep(1)
        snapshot("after startup")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        real = [ctx.wrap_socket(socket.create_connection(("127.0.0.1", or_port),
                                                         5))
                for _ in range(N_REAL)]
        time.sleep(1)
        snapshot("%d real TLS connections open" % N_REAL)

        os.kill(tor.pid, signal.SIGSTOP)
        for i in range(N_GARBAGE + N_FIN):
            s = socket.create_connection(("127.0.0.1", or_port), 5)
            if rst:
                # Close with an RST instead of a FIN.
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                             struct.pack("ii", 1, 0))
            elif i < N_GARBAGE:
                s.sendall(b"GET / HTTP/1.0\r\n\r\n")
            s.close()
        time.sleep(0.5)
        os.kill(tor.pid, signal.SIGCONT)
        time.sleep(2)
        if rst:
            snapshot("+%d RST while stalled" % (N_GARBAGE + N_FIN))
        else:
            snapshot("+%d non-TLS +%d FIN while stalled" % (N_GARBAGE, N_FIN))

        for s in real:
            s.close()
        time.sleep(2)
        snapshot("real connections closed")
    finally:
        tor.terminate()
        tor.wait(timeout=30)
        shutil.rmtree(datadir, ignore_errors=True)


if __name__ == "__main__":
    main()
