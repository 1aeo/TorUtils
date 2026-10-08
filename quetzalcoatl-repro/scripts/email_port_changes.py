#!/usr/bin/env python3
"""email_port_changes.py - which ports the switch to Policy A / B opened and closed, for the section
"What the switch changed" of EMAIL_DRAFT.txt.

For every affected relay (net/victims.csv) the IPv4 summary of its last descriptor before its first A/B
descriptor (net/netdb.sqlite) is compared with the summary it switched to (A = common.OUR_POLICY,
B = common.NEAR_OPEN). A port is "opened" if the old summary rejects it and the new one accepts it, "closed"
the other way round. Relays without an earlier descriptor (new keys) are left out.

Also: how common A's and B's mail-port mixes were among the other relays with an exit policy (p line not
"reject 1-65535") in the consensus of 2026-10-01 14:00:00, the last before the first A descriptor, and among
all relays in consensuses 2026-05-01 .. 10-01 14:00 (cons_interval).

Usage: python3 -I scripts/email_port_changes.py > net/email_port_changes.log
"""
import collections
import csv
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY  # noqa: E402

ROOT = os.path.dirname(HERE)
KEY = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 465, 587, 993, 995, 3389, 6667]
_cache = {}


def allowed(summary, port):
    if summary not in _cache:
        kind, _, spec = summary.partition(" ")
        s = set()
        for part in spec.split(","):
            if "-" in part:
                a, b = part.split("-")
                s.update(range(int(a), int(b) + 1))
            elif part:
                s.add(int(part))
        _cache[summary] = (kind, s)
    kind, s = _cache[summary]
    return (port in s) if kind == "accept" else (port not in s)


def mail_mix(p):
    a = [allowed(p, x) for x in (25, 110, 143, 465, 587, 993, 995)]
    b_mix = a[1] and a[2] and not any(a[3:])
    a_mix = not any(a)
    return a_mix, b_mix


def main():
    db = sqlite3.connect(os.path.join(ROOT, "net/netdb.sqlite"))
    vic = {r["fp"]: r for r in csv.DictReader(open(os.path.join(ROOT, "net/victims.csv")))}
    n = collections.Counter()
    opened = collections.defaultdict(collections.Counter)
    closed = collections.defaultdict(collections.Counter)
    total_open = collections.Counter()
    total_closed = collections.Counter()
    no_pre = 0
    for fp, r in vic.items():
        pre = db.execute("""SELECT p.summary FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                            WHERE d.fp=? AND d.published < ? ORDER BY d.pub_epoch DESC LIMIT 1""",
                         (fp, r["first_attacker_desc"])).fetchone()
        if not pre:
            no_pre += 1
            continue
        pre = pre[0]
        new = OUR_POLICY if r["first_attacker_class"] == "OUR_POLICY" else NEAR_OPEN
        grp = ("Quetzalcoatl" if r["family"] == "1" else "other") + " -> " + \
              ("A" if new == OUR_POLICY else "B") + (" (was non-exit)" if pre == "reject 1-65535" else "")
        n[grp] += 1
        for port in KEY:
            a0, a1 = allowed(pre, port), allowed(new, port)
            if a1 and not a0:
                opened[grp][port] += 1
                total_open[port] += 1
            if a0 and not a1:
                closed[grp][port] += 1
                total_closed[port] += 1
    print("affected relays with an earlier descriptor:", sum(n.values()), " without (new keys):", no_pre)
    for g in sorted(n):
        print(f"\n{g}: {n[g]} relays")
        print("   opened:", dict(sorted(opened[g].items())))
        print("   closed:", dict(sorted(closed[g].items())))
    print("\nall groups, opened:", dict(sorted(total_open.items())))
    print("all groups, closed:", dict(sorted(total_closed.items())))

    rows = db.execute("SELECT fp, policy FROM cons_entry WHERE va='2026-10-01 14:00:00'").fetchall()
    ex = [p for fp, p in rows if fp not in vic and p and p != "reject 1-65535"]
    am = sum(mail_mix(p)[0] for p in ex)
    bm = [p for p in ex if mail_mix(p)[1]]
    print(f"\n10-01 14:00: {len(ex)} other relays with an exit policy; A's mail mix (all mail closed): {am}; "
          f"B's mail mix (110/143 open, 465/587/993/995 closed): {len(bm)}")
    for p in bm:
        print("   ", p[:160])
    print("   allow 22:", sum(allowed(p, 22) for p in ex), " allow 23:", sum(allowed(p, 23) for p in ex),
          " allow 993 and 995:", sum(allowed(p, 993) and allowed(p, 995) for p in ex))
    fps_b = set()
    allfp = set()
    for fp, p in db.execute("SELECT fp, policy FROM cons_interval WHERE start_va < '2026-10-01 14:49:51'"):
        allfp.add(fp)
        if fp not in vic and p and p != "reject 1-65535" and mail_mix(p)[1]:
            fps_b.add(fp)
    print(f"05-01..10-01 14:00: {len(allfp)} relays in any consensus; other relays ever with B's mail mix: "
          f"{len(fps_b)}")


if __name__ == "__main__":
    main()
