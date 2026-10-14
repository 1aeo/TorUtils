#!/usr/bin/env python3
"""Run the ticket-41339 closed-lab off-vs-on matrix and append to CSV + JSONL.

usage: run_matrix.py <base> <nodes_dir> <reps> <duration> [modes_csv] [loads_csv]

  base   : "patched" (sweeps enforcement submodes) or "unpatched" (no options).
  modes  : subset of observe,0001,0002,both   (patched only; default all)
  loads  : subset of none,fetch,reuse-5,reuse-22,onehop,adapted (default all)

Enforcement is applied to the per-cell target HSDir via SETCONF, then reset:
  observe -> 0/0 ; 0001 -> HSDirOneRequestPerCircuit=1 ;
  0002 -> HSDirRefuseUnknownPrevHop=1 ; both -> 1/1.
Load clients are manual tor-loadclient processes:
  reuse-*  -> ctl 8020 (EVIL_ISO_SESSIONGRP)
  fetch/adapted -> ctl 8021 (stock isolation, one req/circuit)
  onehop   -> ctl 8022 (EVIL_ONEHOP unpublished relay-client)
Target is re-probed per cell (hashring rotates with the consensus; pinned via
long V3AuthVotingInterval for the matrix).
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim
from ctl_lib import Ctl

OUT = os.environ.get("SIM_OUT", "../results")
ALL_MODES = ["observe", "0001", "0002", "both"]
ALL_LOADS = ["none", "fetch", "reuse-5", "reuse-22", "onehop", "adapted"]
# load -> (ctl_port, cookie_path)
LC = {
    "fetch":   (8021, "/root/work/lc-fetch/control_auth_cookie"),
    "adapted": (8021, "/root/work/lc-fetch/control_auth_cookie"),
    "reuse-5": (8020, "/root/work/lc-reuse/control_auth_cookie"),
    "reuse-22":(8020, "/root/work/lc-reuse/control_auth_cookie"),
    "onehop":  (8022, "/root/work/lc-onehop/control_auth_cookie"),
}
ENFORCE = {
    "observe": (0, 0), "0001": (1, 0), "0002": (0, 1), "both": (1, 1),
}
FIELDS = ["mode", "load", "rep", "target_nick", "target_fpr", "flood_onion",
          "duration_s", "wall_s", "load_issued", "load_recv", "load_fail",
          "load_groups", "legit_attempts", "legit_ok", "legit_success_rate",
          "legit_mean_latency_s", "legit_p95_latency_s", "begin_dir_recv",
          "hsdir_circ_reused", "hsdir_unknown_prev_hop", "bytes_written",
          "bytes_read", "circs_created", "circs_closed", "onionskins_ntor_v3",
          "net_onionskins", "net_circs_created", "nontgt_onionskins",
          "nontgt_circs_created", "target_cpu_pct", "target_rss_mb", "error"]


def set_enforce(nodes_dir, nick, one_req, refuse_unknown):
    c = Ctl(sim.ctlport(nick), "%s/%s/control_auth_cookie" % (nodes_dir, nick))
    c.cmd("SETCONF HSDirOneRequestPerCircuit=%d" % one_req)
    c.cmd("SETCONF HSDirRefuseUnknownPrevHop=%d" % refuse_unknown)
    c.close()


def main():
    base = sys.argv[1]
    nodes_dir = sys.argv[2]
    reps = int(sys.argv[3])
    duration = int(sys.argv[4])
    modes = (sys.argv[5].split(",") if len(sys.argv) > 5 and sys.argv[5]
             else (ALL_MODES if base == "patched" else ["unpatched"]))
    loads = (sys.argv[6].split(",") if len(sys.argv) > 6 and sys.argv[6]
             else ALL_LOADS)

    relays, hs, stock = sim.discover(nodes_dir)
    stock_ck = "%s/%s/control_auth_cookie" % (nodes_dir, stock)
    stock_ctl = sim.ctlport(stock)
    print("discovered relays=%s hs=%s stock=%s(ctl %d)" %
          (relays, hs, stock, stock_ctl), flush=True)

    os.makedirs(OUT, exist_ok=True)
    csv_path = OUT + "/results.csv"
    new = not os.path.exists(csv_path)
    csv_f = open(csv_path, "a", newline="")
    w = csv.DictWriter(csv_f, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        w.writeheader()
    jsonl = open(OUT + "/results.jsonl", "a")

    def do(label, enf, load, rep):
        row = dict(mode=label, load=load, rep=rep, duration_s=duration, error="")
        tgt = None
        try:
            tgt = sim.choose_target(nodes_dir, stock_ctl, stock_ck, relays, hs)
            if base == "patched":
                set_enforce(nodes_dir, tgt[0], enf[0], enf[1])
            cfg = dict(mode=label, load=load, rep=rep, nodes_dir=nodes_dir,
                       target=tgt, duration=duration, relays=relays,
                       legit_ctl=stock_ctl, legit_cookie=stock_ck,
                       legit_onion=tgt[2])
            if load != "none":
                cfg["load_ctl"], cfg["load_cookie"] = LC[load]
            row = sim.run_cell(cfg)
            row["error"] = ""
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            try:
                if base == "patched" and tgt:
                    set_enforce(nodes_dir, tgt[0], 0, 0)
            except Exception:
                pass
        w.writerow(row)
        csv_f.flush()
        jsonl.write(json.dumps(row) + "\n")
        jsonl.flush()
        print("[%s] %-9s rep%d tgt=%s reused=%s unkhop=%s recv=%s/%s fail=%s "
              "legit=%s cpu=%s netonion=%s err=%s" % (
                  label, load, rep, row.get("target_nick"),
                  row.get("hsdir_circ_reused"), row.get("hsdir_unknown_prev_hop"),
                  row.get("load_recv"), row.get("load_issued"), row.get("load_fail"),
                  row.get("legit_success_rate"), row.get("target_cpu_pct"),
                  row.get("net_onionskins"), row.get("error")), flush=True)

    for mode in modes:
        enf = ENFORCE.get(mode, (0, 0))
        if "none" in loads:
            do(("unpatched" if base == "unpatched" else "patched-" + mode),
               enf, "none", 1)
        for load in loads:
            if load == "none":
                continue
            for rep in range(1, reps + 1):
                do(("unpatched" if base == "unpatched" else "patched-" + mode),
                   enf, load, rep)

    csv_f.close()
    jsonl.close()
    print("MATRIX_DONE base=%s modes=%s loads=%s" % (base, modes, loads), flush=True)


if __name__ == "__main__":
    main()
