#!/usr/bin/env python3
"""Determine, for each onion service, which relays (by fingerprint) are
responsible HSDirs that return a descriptor (HS_DESC RECEIVED) when asked
directly with HSFETCH ... SERVER=<fpr>.  Prints a table and, on the last
line, a chosen (target_nick target_fpr onion) triple with the most onions
served, for use as the flood target.

usage: probe_hsdirs.py <nodes_dir> <client_ctl_port>
"""
import sys
import time
from ctl_lib import Ctl

nodes_dir, cport = sys.argv[1], int(sys.argv[2])
cport = int(cport)

RELAYS = ["004r", "005r", "006r", "007r", "008r"]
HS = ["011h", "012h", "013h"]


def fpr(nick):
    with open(f"{nodes_dir}/{nick}/fingerprint") as f:
        return f.read().split()[1]


def onion(nick):
    import glob
    hn = glob.glob(f"{nodes_dir}/{nick}/**/hostname", recursive=True)
    return open(hn[0]).read().strip().replace(".onion", "")


relay_fpr = {n: fpr(n) for n in RELAYS}
onions = {n: onion(n) for n in HS}

cookie = f"{nodes_dir}/{__import__('os').path.basename(sys.argv[0]) and '009c'}/control_auth_cookie"
# use 009c stock client
cookie = f"{nodes_dir}/009c/control_auth_cookie"

served = {n: [] for n in RELAYS}
for hs, oaddr in onions.items():
    for rn in RELAYS:
        c = Ctl(cport, cookie)
        c.setevents("HS_DESC")
        f = relay_fpr[rn]
        c.cmd(f"HSFETCH {oaddr} SERVER=${f}")
        evs = c.collect_events(10, match="HS_DESC RECEIVED " + oaddr)
        got = any(("HS_DESC RECEIVED " + oaddr) in l and f in l for _, l in evs)
        fail = any(("HS_DESC FAILED " + oaddr) in l and f in l for _, l in evs)
        status = "RECEIVED" if got else ("FAILED" if fail else "NONE")
        print(f"onion {hs} ({oaddr[:16]}..) <- {rn} {f}: {status}", flush=True)
        if got:
            served[rn].append(hs)
        c.close()
        time.sleep(0.3)

print("=== summary: onions served per relay ===")
for rn in RELAYS:
    print(f"{rn} {relay_fpr[rn]}: {served[rn]}")

# pick target = relay serving the most onions
target = max(RELAYS, key=lambda r: len(served[r]))
tgt_onions = served[target]
print(f"TARGET {target} {relay_fpr[target]} ONIONS {','.join(onions[h] for h in tgt_onions)}")
