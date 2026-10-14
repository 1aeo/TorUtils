#!/usr/bin/env python3
import sys, time
sys.path.insert(0, ".")
from ctl_lib import Ctl
from metrics import scrape

TGT_FPR = "0A613FD99F9C447FDDAA0647CAE069EB0A521E3D"
TGT_METRICS = 19104
ONION = "7op5kxuemugxvs7el7sj6h26tf4bsxqvpaugfru2n6dcqey74f5wqhqd"
CK = "/root/work/lc-reuse/control_auth_cookie"
FETCH = "HSFETCH %s SERVER=$%s" % (ONION, TGT_FPR)


def run(label, fn):
    before = scrape(TGT_METRICS)
    c = Ctl(8020, CK)
    fn(c)
    c.collect_events(4)
    c.close()
    time.sleep(2)
    after = scrape(TGT_METRICS)
    d = {k: (after[k] - before[k]) if after[k] is not None and before[k] is not None else None for k in before}
    print("%-34s begin_dir+=%-3s reused+=%-3s circs_created+=%-3s" % (
        label, d["begin_dir"], d["hsdir_circ_reused"], d["circs_created"]))


def establish_then_spaced(n, gap):
    def fn(c):
        c.cmd(FETCH)              # establish circuit
        c.collect_events(1.5)     # let it build + complete, stays open
        for _ in range(n - 1):
            c.cmd(FETCH)
            time.sleep(gap)
    return fn


run("2 fetches gap=0.3", establish_then_spaced(2, 0.3))
run("5 fetches gap=0.2", establish_then_spaced(5, 0.2))
run("5 fetches gap=0.05", establish_then_spaced(5, 0.05))
run("22 fetches gap=0.1", establish_then_spaced(22, 0.1))
run("22 fetches gap=0.05", establish_then_spaced(22, 0.05))
