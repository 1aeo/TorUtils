#!/usr/bin/env python3
"""net_timeofday.py - UTC hour-of-day of attacker-pattern events vs the same relays' baseline restarts.

Attacker-pattern events: descriptor-level transitions INTO near-open / OUR_POLICY (attacker_transitions.csv,
direction into*), plus victim restarts/reloads during 2026-10-01..10-07.
Baseline: restarts of the same victim relays 2026-05-01..2026-09-30 (drift-filtered, excluding the first
descriptor of each relay).
Descriptive only. Output: net/time_of_day.csv (hour, counts, shares).
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_ts, ts_epoch  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    trans = []
    with open(os.path.join(args.out, "attacker_transitions.csv")) as f:
        for r in csv.DictReader(f):
            if r["direction"].startswith("into") and r["published"] >= "2026-09-01":
                trans.append(r["published"])
    oct1 = ts_epoch("2026-10-01 00:00:00")
    sep30 = ts_epoch("2026-10-01 00:00:00")
    vic_restart_oct = [epoch_ts(be) for (be,) in db.execute(
        "SELECT boot_epoch FROM restart WHERE fp IN (SELECT fp FROM victim) AND boot_epoch >= ? AND first_in_window=0", (oct1,))]
    vic_reload_oct = [epoch_ts(pe) for (pe,) in db.execute(
        "SELECT pub_epoch FROM reload WHERE fp IN (SELECT fp FROM victim) AND pub_epoch >= ?", (oct1,))]
    base = [epoch_ts(be) for (be,) in db.execute(
        "SELECT boot_epoch FROM restart WHERE fp IN (SELECT fp FROM victim) AND boot_epoch < ? AND first_in_window=0", (sep30,))]
    series = {"into_attacker_policy": trans, "victim_restarts_oct": vic_restart_oct,
              "victim_reloads_oct": vic_reload_oct, "victim_restarts_may_sep_baseline": base}
    counts = {k: collections.Counter(int(t[11:13]) for t in v) for k, v in series.items()}
    with open(os.path.join(args.out, "time_of_day.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour_utc"] + [k for k in series] + ["share_" + k for k in series])
        for h in range(24):
            w.writerow([h] + [counts[k][h] for k in series] +
                       ["%.3f" % (counts[k][h] / len(series[k])) if series[k] else "" for k in series])
    for k in series:
        print(k, len(series[k]), "by hour:", [counts[k][h] for h in range(24)])


if __name__ == "__main__":
    main()
