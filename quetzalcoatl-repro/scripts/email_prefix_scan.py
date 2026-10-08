#!/usr/bin/env python3
"""email_prefix_scan.py - rule-order checks for item 1 of EMAIL_DRAFT.txt.

Scans every server descriptor from 2026-01-01 up to the first Policy A descriptor (2026-10-01 14:49:51):
the CollecTor monthly archives data_history/server-descriptors-2026-0[1-4].tar.xz (streamed) and the
descriptor/policy tables of net/netdb.sqlite (descriptors from 2026-04-25). For each descriptor it takes the
ordered list of port specs of its wildcard rules (address "*", "*4" or "0.0.0.0/0"; own-IP and private-net
rules are skipped) up to the final "accept *:*"/"reject *:*".

Reports:
  * distinct descriptors (SHA-1 digest) published 2026-01-01 .. 2026-09-26 06:10:06;
  * descriptors whose wildcard rules START with A's first 7 rules in A's order (25,465,587,110,143,993,995):
    relays, nicknames, IPs, time range, the full rule list;
  * descriptors whose wildcard reject rules are EXACTLY the ports 25,110,143,465,587,993,995 (any order),
    followed by accept *:*: relays, order, time range;
  * for every descriptor whose IPv4 summary is A or B (DB only): the distinct wildcard rule orders.

Usage: python3 -I scripts/email_prefix_scan.py > net/email_prefix_scan.log
"""
import collections
import concurrent.futures as cf
import hashlib
import os
import sqlite3
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY  # noqa: E402

ROOT = os.path.dirname(HERE)
A7 = ["25", "465", "587", "110", "143", "993", "995"]
SEVEN = set(A7)
END_A = "2026-10-01 14:49:51"
END_ITEM1 = "2026-09-26 06:10:06"
WILD = ("*", "*4", "0.0.0.0/0")


def wild_ports(lines):
    out = []
    for ln in lines:
        parts = ln.split()
        if len(parts) != 2 or parts[0] not in ("accept", "reject"):
            continue
        addr, _, port = parts[1].rpartition(":")
        if addr in WILD:
            if port == "*":
                out.append(parts[0] + " *")
                break
            out.append(parts[0] + " " + port)
    return out


def classify(rules):
    rej = [r.split()[1] for r in rules if r.startswith("reject ") and r != "reject *"]
    prefix = rej[:7] == A7 and all(r.startswith("reject ") for r in rules[:7])
    exact7 = set(rej) == SEVEN and len(rej) == 7 and rules and rules[-1] == "accept *"
    return prefix, exact7


def parse_desc(raw):
    nick = ip = pub = fp = None
    pol = []
    for b in raw.split(b"\n"):
        if b.startswith(b"router "):
            p = b.split()
            nick, ip = p[1].decode("utf-8", "replace"), p[2].decode()
        elif b.startswith(b"published "):
            pub = b[10:].decode().strip()
        elif b.startswith(b"fingerprint "):
            fp = b[12:].decode().replace(" ", "").upper()
        elif b.startswith(b"accept ") or b.startswith(b"reject "):
            pol.append(b.decode("utf-8", "replace").strip())
    return fp, nick, ip, pub, pol


def digest(raw):
    s = raw.find(b"router ")
    e = raw.find(b"\nrouter-signature\n")
    if s < 0 or e < 0:
        return None
    return hashlib.sha1(raw[s:e + len(b"\nrouter-signature\n")]).hexdigest()


def scan_archive(path):
    digests = set()
    hits_prefix, hits_exact = [], []
    n = 0
    with tarfile.open(path, "r|xz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            data = tf.extractfile(m).read()
            parts = data.split(b"\n@type server-descriptor")
            for i, raw in enumerate(parts):
                if not raw.strip():
                    continue
                n += 1
                d = digest(raw)
                fp, nick, ip, pub, pol = parse_desc(raw)
                if not pub or pub >= END_A:
                    continue
                if pub < END_ITEM1 and d:
                    digests.add(d)
                rules = wild_ports(pol)
                pre, ex = classify(rules)
                if pre:
                    hits_prefix.append((pub, fp, nick, ip, ",".join(r.split()[1] for r in rules)))
                if ex:
                    hits_exact.append((pub, fp, nick, ip, ",".join(r.split()[1] for r in rules if r.startswith("reject"))))
    return path, n, digests, hits_prefix, hits_exact


def summarize(label, hits):
    by = collections.defaultdict(list)
    for h in hits:
        by[h[1]].append(h)
    print(f"\n== {label}: {len(hits)} descriptors, {len(by)} relays")
    for fp, hs in sorted(by.items(), key=lambda x: min(h[0] for h in x[1])):
        hs.sort()
        orders = sorted({h[4] for h in hs})
        print(f"   {fp} {hs[0][2]:<20} {hs[0][3]:<16} {hs[0][0]} .. {hs[-1][0]} ({len(hs)}) order(s): "
              + " | ".join(o[:150] for o in orders))


def main():
    arcs = [os.path.join(ROOT, f"data_history/server-descriptors-2026-0{m}.tar.xz") for m in (1, 2, 3, 4)]
    allp, alle, digests = [], [], set()
    with cf.ProcessPoolExecutor(4) as ex:
        for path, n, dg, hp, he in ex.map(scan_archive, arcs):
            print(os.path.basename(path), "descriptors:", n, "distinct (to 09-26 06:10:06):", len(dg))
            digests |= dg
            allp += hp
            alle += he
    print("archives 2026-01..04 distinct digests:", len(digests))

    db = sqlite3.connect(os.path.join(ROOT, "net/netdb.sqlite"))
    dbd = set()
    for (d,) in db.execute("SELECT lower(digest) FROM descriptor WHERE published < ?", (END_ITEM1,)):
        dbd.add(d)
    print("DB descriptors before 09-26 06:10:06:", len(dbd), " overlap with archives:", len(dbd & digests),
          " union:", len(dbd | digests))

    pols = {}
    for h, txt, summ in db.execute("SELECT policy_h, text, summary FROM policy"):
        pols[h] = (wild_ports(txt.split("\n")), summ)
    for fp, nick, ip, pub, h in db.execute(
            "SELECT fp, nickname, address, published, policy_h FROM descriptor WHERE published < ?", (END_A,)):
        rules, _ = pols[h]
        pre, ex = classify(rules)
        if pre:
            allp.append((pub, fp, nick, ip, ",".join(r.split()[1] for r in rules)))
        if ex:
            alle.append((pub, fp, nick, ip, ",".join(r.split()[1] for r in rules if r.startswith("reject"))))
    summarize("wildcard rules start with A's first 7 rules in A's order (before 10-01 14:49:51)", allp)
    summarize("wildcard rejects are exactly 25,110,143,465,587,993,995, then accept *:* (before 10-01 14:49:51)",
              alle)

    print("\n== rule orders of all DB descriptors with summary A or B")
    for name, summ in (("A", OUR_POLICY), ("B", NEAR_OPEN)):
        orders = collections.Counter()
        relays = collections.defaultdict(set)
        for fp, h in db.execute("SELECT d.fp, d.policy_h FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h "
                                "WHERE p.summary=?", (summ,)):
            o = ",".join(r.split()[1] for r in pols[h][0])
            orders[o] += 1
            relays[o].add(fp)
        for o, c in orders.items():
            print(f"   {name}: {c} descriptors, {len(relays[o])} relays: {o}")


if __name__ == "__main__":
    main()
