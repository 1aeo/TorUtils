#!/usr/bin/env python3
"""Controlled micro-benchmark (no flood): directly show the 0001 counter
measures per-circuit HSDir-request reuse, and that enforcement refuses the
2nd+ request per circuit.  Loopback only.

For each (load-client, enforcement) it issues a small, fixed burst of
HSFETCH ... SERVER=<target> and reports the target's hsdir_circ_reused and
BEGIN_DIR deltas plus client success.
"""
import sys, time
sys.path.insert(0, ".")
import sim
from ctl_lib import Ctl
from metrics import scrape

nodes = "/root/work/net-patched/nodes"
stock_ck = nodes + "/009c/control_auth_cookie"
tgt = sim.choose_target(nodes, 8009, stock_ck)
tnick, tfpr, oaddr = tgt
mp = 19100 + sim.RELAY_NODENUM[tnick]
print("target=%s fpr=%s onion=%s metrics=%d" % (tnick, tfpr, oaddr, mp))


def set_enforce(on):
    nn = int(tnick[:3])
    c = Ctl(8000 + nn, nodes + "/%s/control_auth_cookie" % tnick)
    c.cmd("SETCONF HSDirOneRequestPerCircuit=%d" % (1 if on else 0))
    c.close()


def burst(label, ctl, ck, n, enforce):
    set_enforce(enforce)
    b = scrape(mp)
    c = Ctl(ctl, ck)
    c.setevents("HS_DESC")
    recv = fail = 0
    for _ in range(n):
        c.cmd("HSFETCH %s SERVER=$%s" % (oaddr, tfpr))
    for _, l in c.collect_events(max(4, n * 0.25)):
        if "HS_DESC RECEIVED " + oaddr in l:
            recv += 1
        elif "HS_DESC FAILED " + oaddr in l:
            fail += 1
    c.close()
    time.sleep(2)
    a = scrape(mp)
    set_enforce(False)
    print("%-32s n=%-3d  reused+=%-3s begin_dir+=%-3s  client recv=%-3d fail=%-3d" % (
        label, n, a["hsdir_circ_reused"] - b["hsdir_circ_reused"],
        a["begin_dir"] - b["begin_dir"], recv, fail))


RE = (8020, "/root/work/lc-reuse/control_auth_cookie")   # EVIL_ISO_SESSIONGRP
FE = (8021, "/root/work/lc-fetch/control_auth_cookie")   # stock isolation

print("--- observe (enforcement off): reuse counted, nothing closed ---")
burst("reuse client (EVIL_ISO) x5", RE[0], RE[1], 5, False)
burst("reuse client (EVIL_ISO) x22", RE[0], RE[1], 22, False)
burst("fetch client (1/circuit) x22", FE[0], FE[1], 22, False)
print("--- enforce (HSDirOneRequestPerCircuit=1 on target) ---")
burst("reuse client (EVIL_ISO) x5", RE[0], RE[1], 5, True)
burst("reuse client (EVIL_ISO) x22", RE[0], RE[1], 22, True)
burst("fetch client (1/circuit) x22", FE[0], FE[1], 22, True)
