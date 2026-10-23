"""Minimal control-port client for a STOCK lab tor client: issue ordinary,
single HSFETCH requests one at a time and report each outcome.
Usage: hsfetch.py <control-socket-path> <onion-address-without-.onion> <count> [<hsdir-fp>,<hsdir-fp>,...]
With a fingerprint list, fetch i goes to SERVER=<list[i % len]> (round-robin);
each fetch waits at most HSFETCH_TIMEOUT seconds (default 30) for its event.
Prints one line per fetch: idx, result (RECEIVED/FAILED), hsdir, reason, secs."""
import socket, sys, time, binascii, os
def ctl_connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(path)
    f = s.makefile("rwb", buffering=0)
    return s, f
def cmd(f, line):
    f.write((line + "\r\n").encode())
    out = []
    while True:
        l = f.readline().decode().rstrip("\r\n")
        out.append(l)
        if len(l) >= 4 and l[3] == " ": return out
def main():
    path, onion, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    servers = sys.argv[4].split(",") if len(sys.argv) > 4 else []
    tmo = float(os.environ.get("HSFETCH_TIMEOUT", "30"))
    s, f = ctl_connect(path)
    cookie = open(os.path.join(os.path.dirname(path), "control_auth_cookie"), "rb").read()
    r = cmd(f, "AUTHENTICATE " + binascii.hexlify(cookie).decode()); assert r[-1].startswith("250"), r
    r = cmd(f, "SETEVENTS HS_DESC"); assert r[-1].startswith("250"), r
    s.settimeout(tmo)
    for i in range(count):
        t0 = time.time()
        extra = f" SERVER={servers[i % len(servers)]}" if servers else ""
        f.write(f"HSFETCH {onion}{extra}\r\n".encode())
        res = None
        while res is None:
            try:
                l = f.readline().decode().rstrip("\r\n")
            except (socket.timeout, TimeoutError):
                res = ("TIMEOUT", "-", f"no HS_DESC event within {tmo:.0f}s")
                break
            if l.startswith("650 HS_DESC "):
                p = l.split()
                if p[2] in ("RECEIVED", "FAILED"):
                    reason = [x for x in p if x.startswith("REASON=")]
                    res = (p[2], p[5] if len(p) > 5 else "?", reason[0] if reason else "")
            elif l.startswith("5"):
                res = ("ERROR", "-", l)
        print(f"{i} {res[0]} {res[1]} {res[2]} {time.time()-t0:.2f}", flush=True)
        time.sleep(float(os.environ.get("HSFETCH_GAP", "0.5")))
main()
