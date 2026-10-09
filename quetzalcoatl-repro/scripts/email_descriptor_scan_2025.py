#!/usr/bin/env python3
"""email_descriptor_scan_2025.py - extends the item-1 descriptor checks of EMAIL_DRAFT.txt to 2025, so that
consensuses and server descriptors cover the same period (2025-01-01 .. 2026-09-26).

Each monthly CollecTor archive server-descriptors-2025-MM.tar.xz is streamed with curl straight into Python's
tarfile (nothing large is written to disk). For every descriptor:
  * distinct descriptors are counted by SHA-1 digest (router .. router-signature);
  * if its wildcard rules end with "accept *:*", its IPv4 summary is computed with common.summarize_policy()
    (the validated re-implementation of tor's policy_summarize) and compared with Policy A and Policy B;
  * its wildcard rules are tested for A's first 7 rules in A's order (25,465,587,110,143,993,995), and for
    rejecting exactly the ports 25,110,143,465,587,993,995 (any order) followed by accept *:*
    (functions from scripts/email_prefix_scan.py).
One JSON file per month is written to net/email_descriptor_scan_2025/; a summary is printed at the end.

Usage: python3 -I scripts/email_descriptor_scan_2025.py > net/email_descriptor_scan_2025.log
"""
import collections
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY, summarize_policy  # noqa: E402
from email_prefix_scan import wild_ports, classify, parse_desc, digest  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "net/email_descriptor_scan_2025")
BASE = "https://collector.torproject.org/archive/relay-descriptors/server-descriptors/"


def scan_month(month):
    path = os.path.join(OUT, f"{month}.json")
    if os.path.exists(path):
        return json.load(open(path))
    url = f"{BASE}server-descriptors-{month}.tar.xz"
    for attempt in range(4):
        proc = subprocess.Popen(["curl", "-sf", "--retry", "5", "--retry-all-errors", url],
                                stdout=subprocess.PIPE)
        digests = set()
        n = 0
        hits = {"A": [], "B": [], "prefix": [], "exact7": []}
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|xz") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    data = tf.extractfile(m).read()
                    for raw in data.split(b"\n@type server-descriptor"):
                        if not raw.strip():
                            continue
                        n += 1
                        d = digest(raw)
                        if d:
                            digests.add(d)
                        fp, nick, ip, pub, pol = parse_desc(raw)
                        rules = wild_ports(pol)
                        pre, ex = classify(rules)
                        row = [pub, fp, nick, ip, ",".join(r.split()[1] for r in rules)]
                        if pre:
                            hits["prefix"].append(row)
                        if ex:
                            hits["exact7"].append(row)
                        if rules and rules[-1] == "accept *":
                            s = summarize_policy(pol)
                            if s == OUR_POLICY:
                                hits["A"].append(row)
                            elif s == NEAR_OPEN:
                                hits["B"].append(row)
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"curl exit {proc.returncode}")
        except Exception as e:  # retry the whole month on a broken stream
            proc.kill()
            print(month, "attempt", attempt + 1, "failed:", e, flush=True)
            continue
        res = {"month": month, "descriptors": n, "distinct": len(digests), **hits}
        json.dump(res, open(path, "w"))
        return res
    raise RuntimeError(f"{month}: all attempts failed")


def main():
    os.makedirs(OUT, exist_ok=True)
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    total = distinct = 0
    agg = collections.defaultdict(list)
    with cf.ProcessPoolExecutor(4) as ex:
        for res in ex.map(scan_month, months):
            print(res["month"], "descriptors", res["descriptors"], "distinct", res["distinct"],
                  "A", len(res["A"]), "B", len(res["B"]), "A-order 7-prefix", len(res["prefix"]),
                  "exactly 7 mail ports", len(res["exact7"]), flush=True)
            total += res["descriptors"]
            distinct += res["distinct"]
            for k in ("A", "B", "prefix", "exact7"):
                agg[k] += res[k]
    print("\n2025 total descriptors", total, " distinct (sum of months)", distinct)
    for k in ("A", "B", "prefix", "exact7"):
        by = collections.defaultdict(list)
        for row in agg[k]:
            by[row[1]].append(row)
        print(f"\n== {k}: {len(agg[k])} descriptors, {len(by)} relays")
        for fp, rows in sorted(by.items(), key=lambda x: min(r[0] for r in x[1])):
            rows.sort()
            print(f"   {fp} {rows[0][2]:<20} {rows[0][3]:<16} {rows[0][0]} .. {rows[-1][0]} ({len(rows)}) "
                  f"order(s): {' | '.join(sorted({r[4][:120] for r in rows}))}")


if __name__ == "__main__":
    main()
