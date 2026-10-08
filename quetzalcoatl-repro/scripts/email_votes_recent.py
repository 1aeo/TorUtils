#!/usr/bin/env python3
"""email_votes_recent.py - fill the vote gap after the monthly archive (which ends 2026-10-07 01:00) with the
directory-authority votes in CollecTor recent/ (last ~72 h), for the 377 affected relays only.

Each vote is fetched with curl and parsed in memory (nothing large is written to disk). For every vote:
valid-after, authority nickname, known-flags and number of entries go to net/votes_recent_meta.csv; for every
"r" entry whose fingerprint is one of the 377 affected relays (net/victims.csv), the row
(valid-after, authority, fingerprint, nickname, descriptor published time from the r line, IP, ORPort,
s-line flags, p line) goes to net/votes_recent_victims.csv.

Usage: python3 -I scripts/email_votes_recent.py --from "2026-10-07 02:00:00" [--to "2026-10-08 13:00:00"]
"""
import argparse
import base64
import concurrent.futures as cf
import csv
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://collector.torproject.org/recent/relay-descriptors/votes/"


def b64_to_hex(b):
    return base64.b64decode(b + "=" * (-len(b) % 4)).hex().upper()


def fetch(url):
    r = subprocess.run(["curl", "-sf", "--retry", "5", "--retry-all-errors", "--retry-delay", "2", url],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl {r.returncode} {url}")
    return r.stdout


def parse(data, targets):
    va = auth = kf = None
    n = 0
    rows = []
    cur = None
    for raw in data.split(b"\n"):
        c = raw[:2]
        if c == b"r ":
            n += 1
            p = raw.split(b" ")
            fp = b64_to_hex(p[2].decode())
            if fp in targets:
                cur = [fp, p[1].decode("utf-8", "replace"), (p[4] + b" " + p[5]).decode(), p[6].decode(),
                       p[7].decode(), "", ""]
                rows.append(cur)
            else:
                cur = None
        elif cur is not None and c == b"s ":
            cur[5] = " ".join(sorted(raw[2:].decode().split()))
        elif cur is not None and c == b"p ":
            cur[6] = raw[2:].decode().strip()
        elif raw.startswith(b"valid-after "):
            va = raw[12:].decode().strip()
        elif raw.startswith(b"known-flags "):
            kf = raw[12:].decode().strip()
        elif raw.startswith(b"dir-source ") and auth is None:
            auth = raw.split()[1].decode()
        elif raw.startswith(b"directory-footer"):
            break
    return va, auth, kf, n, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", default="9999")
    args = ap.parse_args()
    targets = {r["fp"] for r in csv.DictReader(open(os.path.join(ROOT, "net/victims.csv")))}
    index = fetch(BASE).decode()
    names = sorted(set(re.findall(r'href="(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d-vote-[0-9A-F]+-[0-9A-F]+)"', index)))

    def va_of(name):
        return name[:10] + " " + name[11:19].replace("-", ":")
    names = [n for n in names if args.start <= va_of(n) <= args.end]
    print("vote files:", len(names), va_of(names[0]), "..", va_of(names[-1]))

    def job(name):
        return name, parse(fetch(BASE + name), targets)
    meta, rows = [], []
    with cf.ThreadPoolExecutor(6) as ex:
        for name, (va, auth, kf, n, rr) in ex.map(job, names):
            meta.append((va, auth, kf, n, name))
            rows += [(va, auth, *r) for r in rr]
    meta.sort()
    rows.sort()
    with open(os.path.join(ROOT, "net/votes_recent_meta.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "authority", "known_flags", "n_entries", "file"])
        w.writerows(meta)
    with open(os.path.join(ROOT, "net/votes_recent_victims.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "authority", "fp", "nickname", "desc_published", "ip", "or_port", "flags",
                    "p"])
        w.writerows(rows)
    rounds = sorted({m[0] for m in meta})
    print("vote rounds:", len(rounds), rounds[0], "..", rounds[-1], " votes:", len(meta),
          " affected-relay rows:", len(rows))
    per = {}
    for m in meta:
        per.setdefault(m[0], []).append(m[1])
    short = {va: a for va, a in per.items() if len(a) < 9}
    print("rounds with fewer than 9 votes:", {va: sorted(set(["bastet", "dannenberg", "dizum", "faravahar",
          "gabelmoo", "longclaw", "maatuska", "moria1", "tor26"]) - set(a)) for va, a in short.items()})


if __name__ == "__main__":
    main()
