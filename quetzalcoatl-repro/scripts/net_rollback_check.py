#!/usr/bin/env python3
"""net_rollback_check.py - for each attacker-related policy change of a victim after 2026-10-04 12:00,
test whether the new policy text is byte-identical to the relay's policy text before its previous change
(a one-step rollback). Output: net/rollback_check.csv
"""
import csv
import sqlite3

db = sqlite3.connect("net/netdb.sqlite")
cls = dict(db.execute("SELECT policy_h, class FROM policy"))
rows = []
for fp, nick, pub, oc, nc, nh, kind in db.execute(
        """SELECT fp, nickname, published, old_class, new_class, new_h, kind FROM policy_event
           WHERE published >= '2026-10-04 12:00:00' AND fp IN (SELECT fp FROM victim) ORDER BY pub_epoch"""):
    hist = db.execute("SELECT published, policy_h FROM descriptor WHERE fp=? AND published < ? ORDER BY pub_epoch",
                      (fp, pub)).fetchall()
    seq = []
    for p, h in hist:
        if not seq or seq[-1][1] != h:
            seq.append((p, h))
    prev2 = seq[-2] if len(seq) >= 2 else None
    rows.append([pub, fp, nick, kind, oc or "", nc, int(bool(prev2) and prev2[1] == nh),
                 prev2[0] if prev2 else "", " > ".join(cls[h] for _, h in seq[-3:])])
with open("net/rollback_check.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["published", "fp", "nickname", "kind", "old_class", "new_class",
                "identical_to_policy_before_previous_change", "that_policy_first_published", "last_classes"])
    w.writerows(rows)
win = [r for r in rows if "2026-10-04 22:15" <= r[0] <= "2026-10-04 22:50"]
print("2026-10-04 22:15-22:50 changes:", len(win), "byte-identical rollbacks:", sum(r[6] for r in win),
      "first descriptors:", sum(1 for r in win if r[3] == "first"))
print("all victim policy changes after 10-04 12:00:", len(rows), "identical rollbacks:", sum(r[6] for r in rows))
