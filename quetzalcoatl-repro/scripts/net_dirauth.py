#!/usr/bin/env python3
"""net_dirauth.py - directory-authority actions seen in the consensus (network-wide).

Outputs (net/):
  consensus_counts.csv        per consensus: relays, Exit, BadExit, MiddleOnly, Guard, Sybil, StaleDesc,
                              policy-class counts, Exit/BadExit/attacker-policy bandwidth weights
  missing_consensuses.csv     hourly valid-after slots absent from the archive
  flag_changes_key.csv        every BadExit / MiddleOnly gain or loss (all relays), every Exit / Guard
                              gain or loss of a victim relay, with after_gap
  flag_batches.csv            flag changes grouped per consensus (batch sizes)
  victim_flag_timeline.csv    per victim: first attacker descriptor, first attacker p-line in consensus,
                              first BadExit / MiddleOnly, removal, still-publishing absences, "missed"
  victim_absences.csv         consensus absences of victims (descriptors published while absent)
  exit_weight_exposure.csv    per consensus from --full-from: Exit-flag weight, usable (non-BadExit)
                              exit weight carried by victims with an attacker p line, share
"""
import argparse
import ast
import collections
import csv
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NEAR_OPEN, OUR_POLICY, parse_ts, fmt_ts  # noqa: E402

ATTP = (NEAR_OPEN, OUR_POLICY)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    vas = [r[0] for r in db.execute("SELECT va FROM consensus ORDER BY va")]
    # -------------------------------------------------- per-consensus counts + missing hours
    keys = ["n", "Exit", "BadExit", "MiddleOnly", "Guard", "Sybil", "StaleDesc", "Running", "pol:non-exit",
            "pol:near-open", "pol:OUR_POLICY", "pol:accept-list", "pol:other-reject-list", "bw_total",
            "bw_exitflag", "bw_exit_usable", "bw_badexit", "bw_attackerpol", "n_attackerpol_exitflag",
            "n_attackerpol_usable_exit", "bw_attackerpol_usable_exit"]
    with open(os.path.join(args.out, "consensus_counts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after"] + keys)
        for va, counts in db.execute("SELECT va, counts FROM consensus ORDER BY va"):
            c = ast.literal_eval(counts)
            w.writerow([va] + [c.get(k, 0) for k in keys])
    missing = []
    t = parse_ts(vas[0])
    have = set(vas)
    while t <= parse_ts(vas[-1]):
        if fmt_ts(t) not in have:
            missing.append(fmt_ts(t))
        t += dt.timedelta(hours=1)
    with open(os.path.join(args.out, "missing_consensuses.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["missing_valid_after"])
        w.writerows([[m] for m in missing])
    print("consensuses:", len(vas), vas[0], "..", vas[-1], "missing hourly slots:", len(missing), missing)
    # -------------------------------------------------- flag changes
    ch = []
    prev = {}
    for fp, s, e, flags, ag, fs, nick, ip, pol in db.execute(
            "SELECT fp, start_va, end_va, flags, after_gap, first_seen, nickname, ip, policy FROM cons_interval ORDER BY fp, start_va"):
        fl = set(flags.split())
        if fp in prev and not fs:
            pfl = prev[fp]
            for f_ in sorted(fl ^ pfl):
                if f_ in ("BadExit", "MiddleOnly") or (fp in victims and f_ in ("Exit", "Guard")):
                    ch.append((s, fp, nick, ip, "gained" if f_ in fl else "lost", f_, ag, pol, int(fp in victims)))
        elif fs:
            for f_ in ("BadExit", "MiddleOnly"):
                if f_ in fl and s != vas[0]:
                    ch.append((s, fp, nick, ip, "first-seen-with", f_, 0, pol, int(fp in victims)))
        prev[fp] = fl
    ch.sort()
    with open(os.path.join(args.out, "flag_changes_key.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "fp", "nickname", "ip", "event", "flag", "after_gap", "p_line", "victim"])
        w.writerows(ch)
    batches = collections.Counter((c[0], c[4], c[5]) for c in ch)
    vb = collections.Counter((c[0], c[4], c[5]) for c in ch if c[8])
    with open(os.path.join(args.out, "flag_batches.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "event", "flag", "relays", "of_which_victims"])
        for k in sorted(batches):
            w.writerow(list(k) + [batches[k], vb.get(k, 0)])
    print("BadExit/MiddleOnly batches (>=1 relay) from 2026-09-25:")
    for k in sorted(batches):
        if k[0] >= "2026-09-25" and k[2] in ("BadExit", "MiddleOnly"):
            print("   ", k, batches[k], "victims", vb.get(k, 0))
    print("BadExit/MiddleOnly batches of >=3 relays before 2026-09-25:")
    for k in sorted(batches):
        if k[0] < "2026-09-25" and k[2] in ("BadExit", "MiddleOnly") and batches[k] >= 3:
            print("   ", k, batches[k], "victims", vb.get(k, 0))
    # -------------------------------------------------- victims timeline
    rows = []
    for fp in sorted(victims):
        fa = db.execute("""SELECT min(d.published) FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                           WHERE d.fp=? AND p.class IN ('near-open','OUR_POLICY')""", (fp,)).fetchone()[0]
        ivs = db.execute("SELECT start_va, end_va, flags, policy, nickname, ip FROM cons_interval WHERE fp=? ORDER BY start_va",
                         (fp,)).fetchall()
        fa_cons = next((iv[0] for iv in ivs if iv[3] in ATTP), "")
        fa_cons_exit = next((iv[0] for iv in ivs if iv[3] in ATTP and "Exit" in iv[2].split()), "")
        fb = next((iv[0] for iv in ivs if "BadExit" in iv[2].split()), "")
        fm = next((iv[0] for iv in ivs if "MiddleOnly" in iv[2].split()), "")
        n_usable = sum(n for (n,) in db.execute(
            "SELECT n FROM cons_interval WHERE fp=? AND policy IN (?,?) AND (' '||flags||' ') LIKE '% Exit %' "
            "AND (' '||flags||' ') NOT LIKE '% BadExit %'", (fp, NEAR_OPEN, OUR_POLICY)))
        last_end = ivs[-1][1] if ivs else ""
        abs_ = db.execute("SELECT after_va, from_va, to_va, n_missing, final, descs_while_absent, last_desc_while_absent "
                          "FROM absence WHERE fp=? AND to_va >= '2026-09-25' ORDER BY from_va", (fp,)).fetchall()
        fin = [a for a in abs_ if a[4]]
        removed_while_publishing = [a for a in abs_ if a[5] > 0 and a[1] and a[1] >= (fa or "9")[:13]]
        missed = int(bool(fa_cons_exit) and not fb and not fm)
        rows.append([fp, ivs[-1][4] if ivs else "", ivs[-1][5] if ivs else "", fa, fa_cons, fa_cons_exit, fb, fm,
                     n_usable, last_end, int(last_end == vas[-1]), fin[0][1] if fin else "",
                     fin[0][5] if fin else "", fin[0][6] if fin else "", len(removed_while_publishing), missed])
    with open(os.path.join(args.out, "victim_flag_timeline.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "nickname", "ip", "first_attacker_desc", "first_attacker_pline_va",
                    "first_attacker_pline_with_Exit_va", "first_BadExit_va", "first_MiddleOnly_va",
                    "consensuses_usable_exit_with_attacker_pline", "last_consensus_va", "in_final_consensus",
                    "final_absence_from_va", "descs_published_while_finally_absent", "last_desc_while_absent",
                    "absences_while_publishing_after_attack", "missed_never_flagged_though_usable_exit"])
        w.writerows(rows)
    with open(os.path.join(args.out, "victim_absences.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "last_present_va", "absent_from_va", "absent_to_va", "reappeared_va", "n_missing",
                    "final", "descs_while_absent", "last_desc_while_absent"])
        for r in db.execute("SELECT * FROM absence WHERE fp IN (SELECT fp FROM victim) AND to_va >= '2026-09-25' "
                            "ORDER BY from_va, fp"):
            w.writerow(r)
    # -------------------------------------------------- exit-weight exposure
    expo = []
    q = db.execute("""SELECT va, sum(bw), sum(CASE WHEN (' '||flags||' ') LIKE '% Exit %' THEN bw ELSE 0 END),
            sum(CASE WHEN (' '||flags||' ') LIKE '% Exit %' AND (' '||flags||' ') NOT LIKE '% BadExit %' THEN bw ELSE 0 END),
            sum(CASE WHEN policy IN (?,?) AND (' '||flags||' ') LIKE '% Exit %' AND (' '||flags||' ') NOT LIKE '% BadExit %'
                     AND fp IN (SELECT fp FROM victim) THEN bw ELSE 0 END),
            sum(CASE WHEN policy IN (?,?) AND (' '||flags||' ') LIKE '% Exit %' AND (' '||flags||' ') NOT LIKE '% BadExit %'
                     AND fp IN (SELECT fp FROM victim) THEN 1 ELSE 0 END),
            sum(CASE WHEN policy IN (?,?) AND fp IN (SELECT fp FROM victim) THEN 1 ELSE 0 END),
            sum(CASE WHEN (' '||flags||' ') LIKE '% BadExit %' THEN 1 ELSE 0 END),
            sum(CASE WHEN (' '||flags||' ') LIKE '% MiddleOnly %' THEN 1 ELSE 0 END),
            sum(CASE WHEN fp IN (SELECT fp FROM victim) AND (' '||flags||' ') LIKE '% BadExit %' THEN 1 ELSE 0 END),
            sum(CASE WHEN fp IN (SELECT fp FROM victim) AND (' '||flags||' ') LIKE '% MiddleOnly %' THEN 1 ELSE 0 END),
            count(*)
            FROM cons_entry GROUP BY va ORDER BY va""", ATTP + ATTP + ATTP)
    for r in q:
        expo.append(list(r) + [round(100.0 * r[4] / r[3], 3) if r[3] else 0])
    with open(os.path.join(args.out, "exit_weight_exposure.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "bw_total", "bw_exit_flag", "bw_exit_usable", "bw_victims_attacker_usable_exit",
                    "n_victims_attacker_usable_exit", "n_victims_attacker_pline", "n_badexit", "n_middleonly",
                    "n_victims_badexit", "n_victims_middleonly", "n_relays", "pct_usable_exit_weight_victims"])
        w.writerows(expo)
    print("exit-weight exposure (victims with attacker p line, Exit, not BadExit), from 2026-09-30 22:00:")
    for r in expo:
        if r[0] >= "2026-09-30 22:00:00":
            print("   %s usable_exit_victims=%d/%d pline=%d share=%.3f%% BadExit=%d (victims %d) MiddleOnly=%d (victims %d)"
                  % (r[0], r[5], r[11], r[6], r[12], r[7], r[9], r[8], r[10]))
    print("victims never BadExit/MiddleOnly although usable exit with attacker p line:", sum(r[15] for r in rows))


if __name__ == "__main__":
    main()
