#!/usr/bin/env python3
"""Aggregate results.csv into per-(mode,load) means for the summary table."""
import csv
import statistics
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    "../results/results.csv"

rows = list(csv.DictReader(open(path)))


def num(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


groups = {}
for r in rows:
    if r.get("error"):
        continue
    groups.setdefault((r["mode"], r["load"]), []).append(r)

MODE_ORDER = ["unpatched", "patched-observe", "patched-0001-enforce"]
LOAD_ORDER = ["none", "fetch", "reuse-5", "reuse-22"]


def agg(rs, key):
    vals = [num(r.get(key)) for r in rs]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return statistics.mean(vals)


hdr = ["mode", "load", "reps", "load_issued", "load_recv", "load_served_frac",
       "reused", "begin_dir", "bytes_written", "circs_closed", "cpu%", "rss_mb",
       "legit_ok/att", "legit_rate", "legit_lat_s"]
print("\t".join(hdr))
for mode in MODE_ORDER:
    for load in LOAD_ORDER:
        rs = groups.get((mode, load))
        if not rs:
            continue
        iss = agg(rs, "load_issued")
        rcv = agg(rs, "load_recv")
        served = (rcv / iss) if (iss and rcv is not None and iss > 0) else None
        la = agg(rs, "legit_attempts")
        lo = agg(rs, "legit_ok")
        row = [
            mode, load, str(len(rs)),
            "%.0f" % iss if iss is not None else "-",
            "%.0f" % rcv if rcv is not None else "-",
            "%.2f" % served if served is not None else "-",
            "%.1f" % agg(rs, "hsdir_circ_reused") if agg(rs, "hsdir_circ_reused") is not None else "NA",
            "%.0f" % agg(rs, "begin_dir_recv") if agg(rs, "begin_dir_recv") is not None else "-",
            "%.0f" % agg(rs, "bytes_written") if agg(rs, "bytes_written") is not None else "-",
            "%.0f" % agg(rs, "circs_closed") if agg(rs, "circs_closed") is not None else "-",
            "%.2f" % agg(rs, "target_cpu_pct") if agg(rs, "target_cpu_pct") is not None else "-",
            "%.0f" % agg(rs, "target_rss_mb") if agg(rs, "target_rss_mb") is not None else "-",
            "%.0f/%.0f" % (lo, la) if (lo is not None and la is not None) else "-",
            "%.3f" % agg(rs, "legit_success_rate") if agg(rs, "legit_success_rate") is not None else "-",
            "%.3f" % agg(rs, "legit_mean_latency_s") if agg(rs, "legit_mean_latency_s") is not None else "-",
        ]
        print("\t".join(row))
