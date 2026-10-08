#!/usr/bin/env python3
"""email_list_publishing.py - the appendix of EMAIL_DRAFT.txt: affected relays that are not in the newest
consensus but published a descriptor with Policy A or B in the 24 h before it (net/email_status_now.csv,
written by scripts/email_status_now.py).

For each relay: nickname, fingerprint and the ContactInfo of its newest descriptor (CollecTor files in
data_recent/, else net/netdb.sqlite). Relays are split by whether at least one authority voted them Running
in the newest vote round, then grouped by contact string (no contact = "(no contact line)"). ContactInfo
strings longer than 60 characters that use "key:value" fields (e.g. ContactInfo Information Sharing
Specification) are shortened to their leading free text plus the email: and url: fields.

Usage: python3 -I scripts/email_list_publishing.py > net/email_list_publishing.txt
"""
import collections
import csv
import re
import glob
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_netdb import parse_descriptor  # noqa: E402
from email_current_status import split_descriptors  # noqa: E402

ROOT = os.path.dirname(HERE)


def short(c):
    if len(c) <= 60 or not re.search(r"(^|\s)email:", c):
        return c
    toks = c.split()
    out, cur = [], None
    for t in toks:
        m = re.match(r"^([a-z0-9]+):", t)
        if m:
            cur = m.group(1)
        if cur is None or cur in ("email", "url"):
            out.append(t)
    return " ".join(out)


def main():
    rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "net/email_status_now.csv")))
            if r["status"] == "publishing" and r["newest_class"] in ("A", "B")]
    want = {r["fp"] for r in rows}
    contact, pubs = {}, {}
    for path in sorted(glob.glob(os.path.join(ROOT, "data_recent/server-descriptors/*"))):
        for d in split_descriptors(open(path, "rb").read()):
            p = parse_descriptor(d)
            fp = p.get("fingerprint")
            if fp in want and (fp not in pubs or p["published"] > pubs[fp]):
                pubs[fp] = p["published"]
                contact[fp] = p.get("contact") or ""
    db = sqlite3.connect(os.path.join(ROOT, "net/netdb.sqlite"))
    for fp in want - set(contact):
        r = db.execute("""SELECT c.text FROM descriptor d LEFT JOIN contact c ON c.contact_h=d.contact_h
                          WHERE d.fp=? ORDER BY d.pub_epoch DESC LIMIT 1""", (fp,)).fetchone()
        contact[fp] = (r[0] if r and r[0] else "")
    for title, sel in (("Reachable (>= 1 authority votes it Running)", lambda r: r["votes_running"] != "0"),
                       ("Not reachable (no authority votes it Running)", lambda r: r["votes_running"] == "0")):
        grp = collections.defaultdict(list)
        for r in rows:
            if sel(r):
                grp[short(contact[r["fp"]]) or "(no contact line)"].append(r)
        n = sum(len(v) for v in grp.values())
        print(f"{title}: {n} relays, {len(grp)} contacts")
        for c in sorted(grp, key=lambda c: (c == "(no contact line)", c.lower())):
            for r in sorted(grp[c], key=lambda r: (r["nickname"].lower(), r["fp"])):
                print(f"{r['nickname']} | {r['fp']} | {c}")
            print()


if __name__ == "__main__":
    main()
