#!/usr/bin/env python3
"""Run the ticket-41339 closed-lab off-vs-on matrix for one mode and append
results to a CSV + JSON log.

usage: run_matrix.py <mode> <nodes_dir> <enforce:0|1> <reps> <duration>

mode is a label (unpatched | patched-observe | patched-0001-enforce).
For enforce=1 the target relay gets HSDirOneRequestPerCircuit=1 (via SETCONF)
for the duration of each cell, then reset to 0.  Load clients are the manual
tor-loadclient processes: reuse -> ctl 8020 (EVIL_ISO_SESSIONGRP), fetch ->
ctl 8021 (stock isolation).  Target is re-probed per cell (the HSDir hashring
rotates with the consensus).
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim
from ctl_lib import Ctl

OUT = "../results"
LOADS = ["fetch", "reuse-5", "reuse-22"]
LC = {
    "fetch": (8021, "/root/work/lc-fetch/control_auth_cookie"),
    "reuse-5": (8020, "/root/work/lc-reuse/control_auth_cookie"),
    "reuse-22": (8020, "/root/work/lc-reuse/control_auth_cookie"),
}
FIELDS = ["mode", "load", "rep", "target_nick", "target_fpr", "flood_onion",
          "duration_s", "wall_s", "load_issued", "load_recv", "load_fail",
          "load_groups", "legit_attempts", "legit_ok", "legit_success_rate",
          "legit_mean_latency_s", "legit_p95_latency_s", "begin_dir_recv",
          "hsdir_circ_reused", "hsdir_unknown_prev_hop", "bytes_written",
          "bytes_read", "circs_created", "circs_closed", "onionskins_ntor_v3",
          "target_cpu_pct", "target_rss_mb", "error"]


def set_enforce(nodes_dir, nick, on):
    nn = int(nick[:3])
    c = Ctl(8000 + nn, "%s/%s/control_auth_cookie" % (nodes_dir, nick))
    c.cmd("SETCONF HSDirOneRequestPerCircuit=%d" % (1 if on else 0))
    c.close()


def main():
    mode, nodes_dir, enforce, reps, duration = (
        sys.argv[1], sys.argv[2], sys.argv[3] == "1",
        int(sys.argv[4]), int(sys.argv[5]))
    stock_ck = nodes_dir + "/009c/control_auth_cookie"
    os.makedirs(OUT, exist_ok=True)
    csv_path = OUT + "/results.csv"
    new = not os.path.exists(csv_path)
    csv_f = open(csv_path, "a", newline="")
    w = csv.DictWriter(csv_f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader()
    jsonl = open(OUT + "/results.jsonl", "a")

    def do(load, rep):
        row = dict(mode=mode, load=load, rep=rep, duration_s=duration, error="")
        try:
            tgt = sim.choose_target(nodes_dir, 8009, stock_ck)
            if enforce:
                set_enforce(nodes_dir, tgt[0], True)
            cfg = dict(mode=mode, load=load, rep=rep, nodes_dir=nodes_dir,
                       target=tgt, duration=duration,
                       legit_ctl=8009, legit_cookie=stock_ck, legit_onion=tgt[2])
            if load != "none":
                cfg["load_ctl"], cfg["load_cookie"] = LC[load]
            row = sim.run_cell(cfg)
            row["error"] = ""
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            try:
                if enforce and "target_nick" in row:
                    set_enforce(nodes_dir, row["target_nick"], False)
            except Exception:
                pass
        w.writerow(row)
        csv_f.flush()
        jsonl.write(json.dumps(row) + "\n")
        jsonl.flush()
        print("[%s] %-20s rep%d tgt=%s reused=%s recv=%s/%s fail=%s legit=%s cpu=%s err=%s" % (
            mode, load, rep, row.get("target_nick"), row.get("hsdir_circ_reused"),
            row.get("load_recv"), row.get("load_issued"), row.get("load_fail"),
            row.get("legit_success_rate"), row.get("target_cpu_pct"), row.get("error")),
            flush=True)

    # no-load baseline (one rep)
    do("none", 1)
    for load in LOADS:
        for rep in range(1, reps + 1):
            do(load, rep)

    csv_f.close()
    jsonl.close()
    print("MATRIX_MODE_DONE %s" % mode, flush=True)


if __name__ == "__main__":
    main()
