#!/usr/bin/env python3
import sys, time
sys.path.insert(0, ".")
from ctl_lib import Ctl
from metrics import scrape

TGT_FPR = "0A613FD99F9C447FDDAA0647CAE069EB0A521E3D"  # 004r
TGT_METRICS = 19104
ONION = "7op5kxuemugxvs7el7sj6h26tf4bsxqvpaugfru2n6dcqey74f5wqhqd"


def test(label, ctlport, cookie, n, groups=1):
    before = scrape(TGT_METRICS)
    c = Ctl(ctlport, cookie)
    for _ in range(groups):
        c.burst(["HSFETCH %s SERVER=$%s" % (ONION, TGT_FPR)] * n)
        c.collect_events(3)
    c.close()
    time.sleep(2)
    after = scrape(TGT_METRICS)
    d = {k: (after[k] - before[k]) if after[k] is not None and before[k] is not None else None for k in before}
    print("%-20s n=%d groups=%d  begin_dir+=%s  reused+=%s  circs_created+=%s  onionskins+=%s  bytes_w+=%s" % (
        label, n, groups, d["begin_dir"], d["hsdir_circ_reused"], d["circs_created"],
        d["onionskins_ntor_v3"], d["bytes_written"]))


test("REUSE pipelined", 8020, "/root/work/lc-reuse/control_auth_cookie", 5, 1)
test("REUSE pipelined", 8020, "/root/work/lc-reuse/control_auth_cookie", 22, 1)
test("FETCH pipelined", 8021, "/root/work/lc-fetch/control_auth_cookie", 5, 1)
test("FETCH pipelined", 8021, "/root/work/lc-fetch/control_auth_cookie", 22, 1)
