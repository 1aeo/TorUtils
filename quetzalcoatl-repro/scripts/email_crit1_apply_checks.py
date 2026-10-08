"""email_crit1_apply_checks.py - re-checks run while applying critique round 1 to the reply draft.

Checks (read-only on net/netdb.sqlite; standard library only; run as python3 -I):
  1. TorDola precursor: ordered wildcard reject/accept rules of the 4 TorDola relays,
     2026-09-01 .. 2026-10-01 15:00, flagging the 7-rule OUR_POLICY prefix
     (reject *:25,465,587,110,143,993,995 in that order).
  2. Flags around the 10-05 12:00 gap: per consensus 10-05 10:00/11:00/12:00, relays with a
     near-open or OUR_POLICY p line, how many carry BadExit/MiddleOnly, and victims flagged.
  3. Usable attacker exit weight 10-04 18:00 .. 10-05 16:00 from net/exit_weight_exposure.csv.
  4. Optional: unique server-descriptor digests before 2026-10-01 = DB digests plus the
     *.digests files written by email_review_history.py (pass their directory as argv[1]).

Usage: python3 -I scripts/email_crit1_apply_checks.py [DIGESTS_DIR]
"""
import csv
import glob
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "net", "netdb.sqlite")
TORDOLA = ["15CA183DC161A0AF6FACDD7A0B6DA84C593E8D09", "4F72DEF09B015E9B6F210597083D95D8A3BC38AD",
           "8B2CCF2A27D52CEE3DC055C1AD11E3755104F601", "C6AA7656909FA64A03EFBA40DD294D4BD79AA3E0"]
PREFIX7 = ["reject *:%s" % p for p in ("25", "465", "587", "110", "143", "993", "995")]
ATT = (common.NEAR_OPEN, common.OUR_POLICY)


def wild(text):
    return [l.strip() for l in text.splitlines() if l.strip().startswith(("reject *:", "accept *:"))]


def main():
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    print("1. TorDola policy changes (ordered wildcard rules)")
    for fp in TORDOLA:
        prev = None
        for pub, ph, text in db.execute(
                "select d.published, d.policy_h, p.text from descriptor d join policy p using(policy_h) "
                "where d.fp=? and d.published>='2026-09-01' and d.published<'2026-10-01 15:00' "
                "order by d.published", (fp,)):
            if ph != prev:
                w = wild(text)
                print(" ", fp, pub, ",".join(r.split(":")[1] for r in w[:12]),
                      "PREFIX7" if w[:7] == PREFIX7 else "")
                prev = ph
    print("2. Flags on attacker p lines")
    vic = set(r[0] for r in db.execute("select fp from victim"))
    for va in ("2026-10-05 10:00:00", "2026-10-05 11:00:00", "2026-10-05 12:00:00"):
        att = attfl = vfl = 0
        for fp, flags, pol in db.execute("select fp, flags, policy from cons_entry where va=?", (va,)):
            f = set(flags.split())
            fl = "BadExit" in f or "MiddleOnly" in f
            if pol in ATT:
                att += 1
                attfl += fl
            if fp in vic and fl:
                vfl += 1
        print("  %s attacker_p=%d attacker_p_flagged=%d victims_flagged=%d" % (va, att, attfl, vfl))
    print("3. Usable attacker exit weight")
    with open(os.path.join(BASE, "net", "exit_weight_exposure.csv")) as fh:
        for r in csv.DictReader(fh):
            if "2026-10-04 18:00:00" <= r["valid_after"] <= "2026-10-05 16:00:00":
                print("  %s n=%s pct=%s" % (r["valid_after"], r["n_victims_attacker_usable_exit"],
                                           r["pct_usable_exit_weight_victims"]))
    if len(sys.argv) > 1:
        d = set()
        for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.digests"))):
            with open(f) as fh:
                d.update(l.strip().upper() for l in fh if l.strip())
        a = len(d)
        n = 0
        for (g,) in db.execute("select digest from descriptor where published<'2026-10-01'"):
            n += 1
            d.add(g.upper())
        print("4. unique archive digests=%d db rows=%d union=%d" % (a, n, len(d)))


if __name__ == "__main__":
    main()
