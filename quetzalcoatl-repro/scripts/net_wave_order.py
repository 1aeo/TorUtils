#!/usr/bin/env python3
"""net_wave_order.py - host-order tests for the attacker-policy waves, with ties handled.

For each wave of waves_15min_events.csv (and for its family / non-family subsets) the hosts are ordered by
their first event (seconds). Inversions are counted only over host pairs whose first events have
DIFFERENT timestamps (same-second events are treated as unordered / parallel), against:
  str   = plain string sort of dotted IPs
  num   = numeric IPv4 sort
  nodot = string sort with the dots removed (what a locale-aware `sort` that ignores punctuation does)
A random order gives about half of the comparable pairs inverted.
Output: net/wave_host_order.csv
"""
import csv
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ip_int, ts_epoch  # noqa: E402


def stats(hosts_t):
    keys = {"str": lambda h: h, "num": ip_int, "nodot": lambda h: h.replace(".", "")}
    n = len(hosts_t)
    out = {"hosts": n}
    comparable = 0
    inv = collections.Counter()
    for i in range(n):
        for j in range(i + 1, n):
            (hi, ti), (hj, tj) = hosts_t[i], hosts_t[j]
            if ti == tj:
                continue
            comparable += 1
            for k, f in keys.items():
                if f(hi) > f(hj):
                    inv[k] += 1
    out["comparable_pairs"] = comparable
    for k in keys:
        out["inv_" + k] = inv[k]
        out["frac_" + k] = round(inv[k] / comparable, 3) if comparable else ""
    return out


def main():
    rows = list(csv.DictReader(open("net/waves_15min_events.csv")))
    by = collections.defaultdict(list)
    for r in rows:
        by[r["wave"]].append(r)
    out = []
    for w, evs in sorted(by.items(), key=lambda kv: int(kv[0])):
        for subset, sel in (("all", lambda r: True), ("family", lambda r: r["family"] == "1"),
                            ("non-family", lambda r: r["family"] == "0")):
            es = [r for r in evs if sel(r)]
            first = {}
            for r in sorted(es, key=lambda r: r["published"]):
                if r["ip"] not in first:
                    first[r["ip"]] = ts_epoch(r["published"])
            hosts_t = sorted(first.items(), key=lambda kv: (kv[1], kv[0]))
            if len(hosts_t) < 3:
                continue
            s = stats(hosts_t)
            out.append([w, subset, es[0]["published"], es[-1]["published"], len(es), s["hosts"], s["comparable_pairs"],
                        s["inv_str"], s["frac_str"], s["inv_num"], s["frac_num"], s["inv_nodot"], s["frac_nodot"],
                        " ".join(h for h, _ in hosts_t)])
    with open("net/wave_host_order.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["wave", "subset", "start", "end", "events", "hosts", "comparable_pairs", "inv_str", "frac_str",
                     "inv_num", "frac_num", "inv_nodot", "frac_nodot", "host_order"])
        wr.writerows(out)
    for r in out:
        print(r[:13])


if __name__ == "__main__":
    main()
