#!/usr/bin/env python3
"""net_victimhost_sync.py - synchronized events on later-victim hosts (precursor test, May-October).

Takes every restart (drift-filtered, boot time in seconds) and reload on the NON-family hosts that later
carried a victim relay, chains them with gaps <= 10 minutes, and keeps chains touching >= 3 hosts of
>= 2 operators (exact contact; relays without contact are separate operators). Reports per month and
lists every chain, flagging the days 2026-08-25..2026-08-31. Output: net/victimhost_sync_chains.csv
"""
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_ts  # noqa: E402

db = sqlite3.connect("net/netdb.sqlite")
contact = dict(db.execute("SELECT contact_h, text FROM contact"))
fam_ct = {h for h, t in contact.items() if t.startswith("email:Quetzalcoatl_relays[]proton.me")}
v = list(csv.DictReader(open("net/victims.csv")))
hosts = {r["ip"] for r in v if r["family"] == "0"}
for (ip,) in db.execute("SELECT DISTINCT address FROM descriptor WHERE fp IN (SELECT fp FROM victim)"):
    pass
ev = []
for fp, t, addr, ch, typ in db.execute(
        "SELECT fp, boot_epoch, address, contact_h, 'restart' FROM restart WHERE first_in_window=0 "
        "UNION ALL SELECT fp, pub_epoch, address, contact_h, 'reload' FROM reload"):
    if addr in hosts and ch not in fam_ct:
        op = contact.get(ch, "(no contact) " + fp[:8]) if ch != "-" else "(no contact) " + fp[:8]
        ev.append((t, addr, fp, op, typ))
ev.sort()
chains, cur = [], []
for e in ev:
    if cur and e[0] - cur[-1][0] > 600:
        chains.append(cur)
        cur = []
    cur.append(e)
chains.append(cur)
rows = []
per = collections.Counter()
for c in chains:
    hs = {e[1] for e in c}
    ops = {e[3] for e in c}
    if len(hs) >= 3 and len(ops) >= 2:
        m = epoch_ts(c[0][0])[:7]
        per[m] += 1
        rows.append([epoch_ts(c[0][0]), epoch_ts(c[-1][0]), len(hs), len(ops), len(c),
                     "; ".join("%s=%d" % kv for kv in collections.Counter(e[4] for e in c).items()),
                     int("2026-08-25" <= epoch_ts(c[0][0]) < "2026-09-01"),
                     " || ".join(sorted(o[:40] for o in ops)), " ".join(sorted(hs))])
with open("net/victimhost_sync_chains.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["start", "end", "hosts", "operators", "events", "types", "aug25_31", "operators_list", "hosts_list"])
    w.writerows(rows)
print("non-family later-victim hosts:", len(hosts), "events:", len(ev))
print("chains (<=10 min, >=3 hosts, >=2 operators) per month:", sorted(per.items()))
for r in rows:
    print("  ", r[:7], r[7][:150])
