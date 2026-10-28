#!/usr/bin/env python3
"""Inside the lab container: drive five load clients at one HSDir, run
operator/begindir-breakdown.py against it while loaded and at the end, and
print the nonzero series of the proposed families.

  reuse            descriptor fetches multiplexed on shared circuits, through
                   relays (a previous hop we know)
  onehop-unlisted  one-hop fetches from an unpublished relay identity
  onehop-client    one-hop fetches from a plain client (answered 503)
  empty-mixed      on one shared circuit, every second fetch opens its
                   BEGIN_DIR stream and never sends its request; that
                   circuit is closed 35 s in
  empty-only       on one shared circuit, every fetch's stream stays empty;
                   left to the stall timeouts (TestingDirConnectionMaxStall:
                   30 s in a test network, on both ends)
"""
import subprocess, sys, threading, time
sys.path.insert(0, "/sim")
import sim
from ctl_lib import Ctl
NODES = sys.argv[1]
STALL = 30  # TestingDirConnectionMaxStall in a test network

def boot(port, ck):
    end = time.time() + 300
    while time.time() < end:
        try:
            c = Ctl(port, ck, timeout=10); ok, l = c.cmd("GETINFO status/bootstrap-phase"); c.close()
            if any("PROGRESS=100" in x for x in l): return True
        except Exception: pass
        time.sleep(3)
    return False

def fetches(port, ck, tfpr, toni, n, gap):
    c = Ctl(port, ck, timeout=20)
    for _ in range(n):
        c.cmd("HSFETCH %s SERVER=$%s" % (toni, tfpr)); time.sleep(gap)
    c.close()

def close_hsdir_circuits(port, ck):
    c = Ctl(port, ck, timeout=20)
    ok, lines = c.cmd("GETINFO circuit-status")
    # "250-circuit-status=ID BUILT ..." for one circuit, else one per line.
    ids = [l.split("circuit-status=", 1)[-1].split()[0] for l in lines
           if "PURPOSE=HS_CLIENT_HSDIR" in l and " BUILT " in l]
    for i in ids:
        c.cmd("CLOSECIRCUIT %s" % i)
    c.close()
    return len(ids)

LCS = {"reuse": (8020, "/work/lc-reuse/control_auth_cookie"),
       "onehop-unlisted": (8022, "/work/lc-onehop/control_auth_cookie"),
       "onehop-client": (8024, "/work/lc-clientonehop/control_auth_cookie"),
       "empty-mixed": (8026, "/work/lc-emptymixed/control_auth_cookie"),
       "empty-only": (8028, "/work/lc-emptyonly/control_auth_cookie")}
for k, (p, ck) in LCS.items():
    print("load client %s bootstrapped: %s" % (k, boot(p, ck)), flush=True)
relays, hs, stock = sim.discover(NODES)
stock_ck = "%s/%s/control_auth_cookie" % (NODES, stock)
tnick, tfpr, toni = sim.choose_target(NODES, sim.ctlport(stock), stock_ck, relays, hs)
open("/work/target", "w").write(tnick)
print("target HSDir %s" % tnick, flush=True)
res = {k: {} for k in LCS}
t0 = time.time()
th = [threading.Thread(target=sim.load_reuse, args=(LCS["reuse"][0], LCS["reuse"][1], tfpr, toni, 70, 5, res["reuse"])),
      threading.Thread(target=sim.load_fetch, args=(LCS["onehop-unlisted"][0], LCS["onehop-unlisted"][1], tfpr, toni, 70, res["onehop-unlisted"])),
      threading.Thread(target=sim.load_fetch, args=(LCS["onehop-client"][0], LCS["onehop-client"][1], tfpr, toni, 70, res["onehop-client"])),
      threading.Thread(target=fetches, args=(LCS["empty-mixed"][0], LCS["empty-mixed"][1], tfpr, toni, 20, 0.5)),
      threading.Thread(target=fetches, args=(LCS["empty-only"][0], LCS["empty-only"][1], tfpr, toni, 20, 0.5))]
for t in th: t.start()
time.sleep(10)
tool = ["python3", "-I", "/tool/begindir-breakdown.py", "--metrics", "http://127.0.0.1:%d/metrics" % sim.mport(tnick),
        "--interval", "45", "--control", "127.0.0.1:%d" % sim.ctlport(tnick),
        "--cookie", "%s/%s/control_auth_cookie" % (NODES, tnick)]
out = {}
def run_tool():
    out["loaded"] = subprocess.run(tool, capture_output=True, text=True).stdout
rt = threading.Thread(target=run_tool); rt.start()
time.sleep(max(0, t0 + 35 - time.time()))
print("closed %d onion service directory circuits of empty-mixed at %.0f s"
      % (close_hsdir_circuits(*LCS["empty-mixed"]), time.time() - t0), flush=True)
rt.join()
print("=== rates while loaded ===", flush=True)
print(out["loaded"], flush=True)
for t in th: t.join()
print("loads:", {k: v for k, v in res.items() if v}, flush=True)
# Let the streams left empty reach the stall timeout, and be counted.
time.sleep(max(0, t0 + 70 + STALL - time.time()))
tool[tool.index("--interval") + 1] = "0"
print("=== totals since start, %.0f s after the loads began ===" % (time.time() - t0), flush=True)
r = subprocess.run(tool, capture_output=True, text=True)
print(r.stdout, r.stderr, flush=True)
import urllib.request
raw = urllib.request.urlopen("http://127.0.0.1:%d/metrics" % sim.mport(tnick),
                             timeout=30).read().decode()
print("=== nonzero series of the proposed families at the target ===", flush=True)
for l in raw.splitlines():
    if l.startswith(("tor_relay_begindir_request_position_total",
                     "tor_relay_begindir_empty_stream_total",
                     "tor_relay_dos_response_bytes_total",
                     "tor_relay_hsdir_descriptor_bytes_total",
                     "tor_relay_begindir_circuit_total",
                     "tor_relay_begindir_discarded_bytes_total",
                     "tor_relay_begindir_pending_bytes")) \
            and not l.endswith(" 0"):
        print(l, flush=True)
