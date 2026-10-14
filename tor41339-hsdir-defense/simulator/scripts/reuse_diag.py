#!/usr/bin/env python3
import sys, time, re
sys.path.insert(0, ".")
from ctl_lib import Ctl
from metrics import scrape

TGT_FPR = "0A613FD99F9C447FDDAA0647CAE069EB0A521E3D"
TGT_METRICS = 19104
ONION = "7op5kxuemugxvs7el7sj6h26tf4bsxqvpaugfru2n6dcqey74f5wqhqd"
CK = "/root/work/lc-reuse/control_auth_cookie"
FETCH = "HSFETCH %s SERVER=$%s" % (ONION, TGT_FPR)


def diag(label, n, gap, wait_recv):
    before = scrape(TGT_METRICS)
    c = Ctl(8020, CK)
    c.setevents("CIRC", "HS_DESC")
    launched = []
    for i in range(n):
        c.cmd(FETCH)
        if wait_recv:
            evs = c.collect_events(3, match="HS_DESC RECEIVED")
        else:
            evs = c.collect_events(gap)
        for _, l in evs:
            m = re.search(r"CIRC (\d+) LAUNCHED.*HS_CLIENT_HSDIR", l)
            if m:
                launched.append(m.group(1))
    c.collect_events(3)
    c.close()
    time.sleep(2)
    after = scrape(TGT_METRICS)
    d = after["hsdir_circ_reused"] - before["hsdir_circ_reused"]
    bd = after["begin_dir"] - before["begin_dir"]
    print("%-26s n=%d  HSDIR circuits launched=%d (distinct=%d)  begin_dir+=%d  reused+=%d" % (
        label, n, len(launched), len(set(launched)), bd, d))


diag("rapid gap=0.0 norecv", 6, 0.0, False)
diag("spaced gap=0.3 norecv", 6, 0.3, False)
diag("wait-RECEIVED between", 6, 0.0, True)
