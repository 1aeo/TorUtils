#!/usr/bin/env python3
"""Inside the lab container: drive three load clients at one HSDir and run
operator/begindir-breakdown.py against it, while loaded and at the end.

  reuse            descriptor fetches multiplexed on shared circuits, through
                   relays (authenticated previous hop we know)
  onehop-unlisted  one-hop fetches from an unpublished relay identity
                   (authenticated previous hop we don't know)
  onehop-client    one-hop fetches from a plain client (unauthenticated;
                   the HSDir answers 503)
"""
import subprocess, sys, threading, time
sys.path.insert(0, "/sim")
import sim
from ctl_lib import Ctl
NODES = sys.argv[1]

def boot(port, ck):
    end = time.time() + 300
    while time.time() < end:
        try:
            c = Ctl(port, ck, timeout=10); ok, l = c.cmd("GETINFO status/bootstrap-phase"); c.close()
            if any("PROGRESS=100" in x for x in l): return True
        except Exception: pass
        time.sleep(3)
    return False

LCS = {"reuse": (8020, "/work/lc-reuse/control_auth_cookie"),
       "onehop-unlisted": (8022, "/work/lc-onehop/control_auth_cookie"),
       "onehop-client": (8024, "/work/lc-clientonehop/control_auth_cookie")}
for k, (p, ck) in LCS.items():
    print("load client %s bootstrapped: %s" % (k, boot(p, ck)), flush=True)
relays, hs, stock = sim.discover(NODES)
stock_ck = "%s/%s/control_auth_cookie" % (NODES, stock)
tnick, tfpr, toni = sim.choose_target(NODES, sim.ctlport(stock), stock_ck, relays, hs)
print("target HSDir %s" % tnick, flush=True)
res = {k: {} for k in LCS}
th = [threading.Thread(target=sim.load_reuse, args=(LCS["reuse"][0], LCS["reuse"][1], tfpr, toni, 70, 5, res["reuse"])),
      threading.Thread(target=sim.load_fetch, args=(LCS["onehop-unlisted"][0], LCS["onehop-unlisted"][1], tfpr, toni, 70, res["onehop-unlisted"])),
      threading.Thread(target=sim.load_fetch, args=(LCS["onehop-client"][0], LCS["onehop-client"][1], tfpr, toni, 70, res["onehop-client"]))]
for t in th: t.start()
time.sleep(10)
cmd = ["python3", "-I", "/tool/begindir-breakdown.py", "--metrics", "http://127.0.0.1:%d/metrics" % sim.mport(tnick),
       "--interval", "45", "--control", "127.0.0.1:%d" % sim.ctlport(tnick),
       "--cookie", "%s/%s/control_auth_cookie" % (NODES, tnick)]
print("=== rates while loaded ===", flush=True)
print(subprocess.run(cmd, capture_output=True, text=True).stdout, flush=True)
for t in th: t.join()
print("loads:", res, flush=True)
time.sleep(3)
cmd[cmd.index("--interval") + 1] = "0"
print("=== totals since start ===", flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout, r.stderr, flush=True)
# The series' counts at the target, and tor 0.4.9.15's own BEGIN_DIR
# counts, nonzero ones only (counts; no identities).
import urllib.request
raw = urllib.request.urlopen("http://127.0.0.1:%d/metrics" % sim.mport(tnick),
                             timeout=30).read().decode()
print("=== nonzero series at the target ===", flush=True)
for l in raw.splitlines():
    if l.startswith(("tor_relay_begindir_", "tor_relay_create_cell",
                     "tor_relay_hsdir_fetch_descriptor",
                     "tor_relay_hsdir_fetch_total{",
                     "tor_relay_hsdir_upload_total{",
                     'tor_relay_dos_total{type="circuit_over_rate"',
                     'tor_relay_dos_total{type="circuit_untracked"',
                     'tor_relay_dos_total{type="hsdir_descriptor_only',
                     'tor_relay_dos_total{type="hsdir_unknown_prev_hop"',
                     'tor_relay_dos_total{type="begindir_')) \
            and not l.endswith(" 0"):
        print(l, flush=True)
