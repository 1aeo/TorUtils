#!/usr/bin/env python3
"""votes_parse.py - stream votes-2026-10.tar.xz (directory-authority votes) into the network DB.

For every vote (one per authority per hour):
  vote(va, auth, auth_fp, known_flags, n_entries, n_exit, n_badexit, n_middleonly, has_badexit_flag,
       has_middleonly_flag, member)
For entries that matter here:
  vote_entry(va, auth, fp, nickname, ip, or_port, flags, policy, desc_published, measured)
    - every entry carrying BadExit or MiddleOnly in any vote (to see who was flagged, and whether
      flagging followed fingerprints or addresses);
    - every entry whose fingerprint is a target (victims, family, relays sharing a victim IP) or
      whose IP is a victim IP.
  vote_absent(va, auth, fp)  target fingerprints that an authority's vote did NOT list
    (an authority that rejects a relay omits it from its vote).

Usage: python3 -I scripts/votes_parse.py --db net/netdb.sqlite --votes data/votes-2026-10.tar.xz
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import iter_tar, b64_to_hex, log  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--votes", default="data/votes-2026-10.tar.xz")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    seeds = set()
    with open(args.seed) as f:
        for line in f:
            t = line.split("#")[0].strip().upper()
            if re.fullmatch(r"[0-9A-F]{40}", t):
                seeds.add(t)
    vic_ips = {r[0] for r in db.execute(
        "SELECT DISTINCT address FROM descriptor WHERE fp IN (SELECT fp FROM victim)")}
    coloc = {r[0] for r in db.execute(
        "SELECT DISTINCT fp FROM descriptor WHERE address IN (SELECT DISTINCT address FROM descriptor "
        "WHERE fp IN (SELECT fp FROM victim)) AND pub_epoch >= strftime('%s','2026-09-01')")}
    fam_hint = {r[0] for r in db.execute(
        "SELECT DISTINCT d.fp FROM descriptor d LEFT JOIN contact c ON c.contact_h=d.contact_h "
        "WHERE lower(d.nickname) LIKE '%quetzal%' OR lower(c.text) LIKE '%quetzal%'")}
    targets = victims | seeds | coloc | fam_hint
    log("targets:", len(targets), "victims:", len(victims), "victim IPs:", len(vic_ips))
    db.executescript("""
      DROP TABLE IF EXISTS vote; DROP TABLE IF EXISTS vote_entry; DROP TABLE IF EXISTS vote_absent;
      CREATE TABLE vote(va TEXT, auth TEXT, auth_fp TEXT, known_flags TEXT, n_entries INTEGER,
        n_exit INTEGER, n_badexit INTEGER, n_middleonly INTEGER, has_badexit_flag INTEGER,
        has_middleonly_flag INTEGER, member TEXT);
      CREATE TABLE vote_entry(va TEXT, auth TEXT, fp TEXT, nickname TEXT, ip TEXT, or_port INTEGER,
        flags TEXT, policy TEXT, desc_published TEXT, measured INTEGER);
      CREATE TABLE vote_absent(va TEXT, auth TEXT, fp TEXT);
    """)
    seen_votes = set()
    for name, data in iter_tar(args.votes):
        va = auth = afp = kf = None
        entries = []
        cur = None
        for raw in data.split(b"\n"):
            c = raw[:2]
            if c == b"r ":
                p = raw.split(b" ")
                cur = [b64_to_hex(p[2].decode()), p[1].decode("utf-8", "replace"), p[6].decode(), int(p[7]),
                       "", "", (p[4] + b" " + p[5]).decode(), None]
                entries.append(cur)
            elif cur is not None and c == b"s ":
                cur[4] = " ".join(sorted(raw[2:].decode().split()))
            elif cur is not None and c == b"p ":
                cur[5] = raw[2:].decode().strip()
            elif cur is not None and c == b"w ":
                m = re.search(rb"Measured=(\d+)", raw)
                cur[7] = int(m.group(1)) if m else None
            elif raw.startswith(b"valid-after "):
                va = raw[12:].decode().strip()
            elif raw.startswith(b"known-flags "):
                kf = raw[12:].decode().strip()
            elif raw.startswith(b"dir-source ") and auth is None:
                p = raw.split()
                auth, afp = p[1].decode(), p[2].decode()
            elif raw.startswith(b"directory-footer"):
                break
        if not va or not auth:
            continue
        if (va, auth) in seen_votes:
            continue
        seen_votes.add((va, auth))
        kfs = set((kf or "").split())
        nb = sum(1 for e in entries if "BadExit" in e[4].split())
        nm = sum(1 for e in entries if "MiddleOnly" in e[4].split())
        ne = sum(1 for e in entries if "Exit" in e[4].split())
        db.execute("INSERT INTO vote VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (va, auth, afp, kf, len(entries), ne, nb, nm, int("BadExit" in kfs),
                    int("MiddleOnly" in kfs), name))
        present = set()
        rows = []
        for fp, nick, ip, orp, flags, pol, dpub, meas in entries:
            present.add(fp)
            fl = flags.split()
            if fp in targets or ip in vic_ips or "BadExit" in fl or "MiddleOnly" in fl:
                rows.append((va, auth, fp, nick, ip, orp, flags, pol, dpub, meas))
        db.executemany("INSERT INTO vote_entry VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO vote_absent VALUES (?,?,?)",
                       [(va, auth, fp) for fp in (victims | coloc) - present])
    db.executescript("""
      CREATE INDEX IF NOT EXISTS ve_fp ON vote_entry(fp, va);
      CREATE INDEX IF NOT EXISTS ve_va ON vote_entry(va);
      CREATE INDEX IF NOT EXISTS va_fp ON vote_absent(fp, va);
    """)
    db.commit()
    log("votes:", len(seen_votes))


if __name__ == "__main__":
    main()
