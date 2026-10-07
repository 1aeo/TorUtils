#!/usr/bin/env python3
"""votes_analysis.py - which directory authorities voted BadExit / MiddleOnly / Exit for which victims, when,
whether they omitted (rejected) victims from their votes, and whether flagging followed fingerprints or
addresses. Input: vote / vote_entry / vote_absent tables written by votes_parse.py (votes-2026-10.tar.xz).

Outputs (net/):
  votes_authority_summary.csv     per authority: votes, known BadExit/MiddleOnly, first hour voting each flag
                                  on an attack victim, max victims flagged, first hour omitting victims
  votes_victim_flags_hourly.csv   per authority and hour: victims listed, voted Exit, BadExit, MiddleOnly
  votes_victim_first_flag.csv     per victim and authority: first BadExit / MiddleOnly vote, first omission
  votes_address_test.csv          relays sharing an IP with a victim but never attacker-policy themselves:
                                  were they flagged / omitted? (address-based vs fingerprint-based action)
  votes_consensus_20261005.csv    for 2026-10-05 10:00-14:00: per authority, family relays listed and flags
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PRE_FLAGGED = "9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76"  # BadExit/MiddleOnly since before October


def has(flags, f):
    return f in flags.split()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    O = lambda n: os.path.join(args.out, n)  # noqa: E731
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")} - {PRE_FLAGGED}
    first_att = dict(db.execute("""SELECT d.fp, min(d.published) FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                                   WHERE p.class IN ('near-open','OUR_POLICY') GROUP BY d.fp"""))
    auths = [r[0] for r in db.execute("SELECT DISTINCT auth FROM vote ORDER BY auth")]
    kf = {a: (bx, mo) for a, bx, mo in db.execute("SELECT auth, max(has_badexit_flag), max(has_middleonly_flag) FROM vote GROUP BY auth")}
    nvotes = dict(db.execute("SELECT auth, count(*) FROM vote GROUP BY auth"))
    vote_vas = collections.defaultdict(set)
    for a, va in db.execute("SELECT auth, va FROM vote"):
        vote_vas[a].add(va)
    ent = collections.defaultdict(dict)   # (auth, va) -> fp -> flags
    for va, a, fp, flags, ip, pol in db.execute("SELECT va, auth, fp, flags, ip, policy FROM vote_entry"):
        ent[(a, va)][fp] = (flags, ip, pol)
    absent = collections.defaultdict(set)
    for va, a, fp in db.execute("SELECT va, auth, fp FROM vote_absent"):
        absent[(a, va)].add(fp)
    vas = sorted({va for (_, va) in ent})
    # hourly
    hourly = []
    for a in auths:
        for va in vas:
            if va not in vote_vas[a]:
                continue
            e = ent.get((a, va), {})
            vl = [fp for fp in victims if fp in e]
            hourly.append([va, a, len(vl), sum(has(e[fp][0], "Exit") for fp in vl),
                           sum(has(e[fp][0], "BadExit") for fp in vl), sum(has(e[fp][0], "MiddleOnly") for fp in vl),
                           len([fp for fp in victims & absent.get((a, va), set()) if first_att.get(fp, "9") <= va])])
    with open(O("votes_victim_flags_hourly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "authority", "victims_listed", "voted_Exit", "voted_BadExit", "voted_MiddleOnly",
                    "victims_omitted_after_first_attacker_desc"])
        w.writerows(hourly)
    # summary per authority
    srows = []
    for a in auths:
        hs = [h for h in hourly if h[1] == a]
        fb = next((h[0] for h in hs if h[4] > 0), "")
        fm = next((h[0] for h in hs if h[5] > 0), "")
        fo = next((h[0] for h in hs if h[6] > 0), "")
        srows.append([a, nvotes[a], kf[a][0], kf[a][1], fb, max(h[4] for h in hs), fm, max(h[5] for h in hs), fo,
                      max(h[6] for h in hs)])
    with open(O("votes_authority_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["authority", "votes", "knows_BadExit", "knows_MiddleOnly", "first_va_BadExit_on_victim",
                    "max_victims_BadExit", "first_va_MiddleOnly_on_victim", "max_victims_MiddleOnly",
                    "first_va_omitting_victims", "max_victims_omitted"])
        w.writerows(srows)
    print("authorities:")
    for r in srows:
        print("   ", r)
    print("hourly totals across authorities (selected hours):")
    for va in vas:
        if va >= "2026-10-04 12:00:00" and va <= "2026-10-05 16:00:00":
            hs = {h[1]: h for h in hourly if h[0] == va}
            print("   ", va, " ".join("%s:L%d/E%d/B%d/M%d/O%d" % (a[:4], hs[a][2], hs[a][3], hs[a][4], hs[a][5], hs[a][6])
                                       for a in auths if a in hs))
    # per victim first flag per authority
    vrows = []
    for fp in sorted(victims):
        row = [fp, first_att.get(fp, "")]
        for a in auths:
            fb = fm = fo = ""
            for va in vas:
                e = ent.get((a, va), {})
                if fp in e:
                    if not fb and has(e[fp][0], "BadExit"):
                        fb = va
                    if not fm and has(e[fp][0], "MiddleOnly"):
                        fm = va
                elif not fo and va in vote_vas[a] and fp in absent.get((a, va), set()) and first_att.get(fp, "9") <= va:
                    fo = va
            row += [fb, fm, fo]
        vrows.append(row)
    with open(O("votes_victim_first_flag.csv"), "w", newline="") as f:
        w = csv.writer(f)
        hdr = ["fp", "first_attacker_desc"]
        for a in auths:
            hdr += [a + "_BadExit", a + "_MiddleOnly", a + "_omitted"]
        w.writerow(hdr)
        w.writerows(vrows)
    never = [r for r in vrows if not any(r[2:])]
    print("victims never flagged nor omitted by any authority:", len(never))
    for r in never:
        print("   ", r[0], r[1])
    # address test: co-located non-victims
    vic_ips = {}
    for fp, ip in db.execute("SELECT DISTINCT fp, address FROM descriptor WHERE fp IN (SELECT fp FROM victim) AND pub_epoch>=strftime('%s','2026-09-25')"):
        vic_ips.setdefault(ip, set()).add(fp)
    arows = []
    seen = set()
    for (a, va), e in ent.items():
        for fp, (flags, ip, pol) in e.items():
            if fp in victims or fp == PRE_FLAGGED or ip not in vic_ips:
                continue
            k = (fp, a)
            if k in seen and not (has(flags, "BadExit") or has(flags, "MiddleOnly")):
                continue
            seen.add(k)
    cand = collections.defaultdict(lambda: {"ip": "", "auth_flagged": set(), "first": "", "omitted": set(), "listed": 0})
    for (a, va), e in ent.items():
        for fp, (flags, ip, pol) in e.items():
            if fp in victims or fp == PRE_FLAGGED or ip not in vic_ips:
                continue
            c = cand[fp]
            c["ip"] = ip
            c["listed"] += 1
            if has(flags, "BadExit") or has(flags, "MiddleOnly"):
                c["auth_flagged"].add(a)
                c["first"] = min(c["first"] or va, va)
    for (a, va), fps in absent.items():
        for fp in fps:
            if fp in cand:
                cand[fp]["omitted"].add(a)
    for fp, c in sorted(cand.items(), key=lambda kv: kv[1]["ip"]):
        nick = db.execute("SELECT nickname FROM descriptor WHERE fp=? ORDER BY pub_epoch DESC LIMIT 1", (fp,)).fetchone()
        arows.append([fp, nick[0] if nick else "", c["ip"], " ".join(sorted(vic_ips[c["ip"]]))[:90],
                      " ".join(sorted(c["auth_flagged"])), c["first"], " ".join(sorted(c["omitted"]))])
    with open(O("votes_address_test.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "nickname", "ip", "victims_on_same_ip", "authorities_flagging_it", "first_flag_va",
                    "authorities_omitting_it_some_hour"])
        w.writerows(arows)
    print("non-victim relays sharing an IP with a victim (seen in votes):", len(arows), "; flagged by >=1 authority:",
          sum(1 for r in arows if r[4]))
    for r in arows:
        print("   ", r[:3], "| flagged by:", r[4] or "-", r[5], "| omitted by:", r[6] or "-")
    # 2026-10-05 consensus anomaly
    fam = {l.split("#")[0].strip().upper() for l in open(args.seed) if len(l.split("#")[0].strip()) == 40}
    fam |= {r[0] for r in db.execute("SELECT DISTINCT fp FROM descriptor WHERE contact_h IN (SELECT contact_h FROM contact WHERE text LIKE 'email:Quetzalcoatl_relays[]proton.me%')")}
    crow = []
    for va in ["2026-10-05 10:00:00", "2026-10-05 11:00:00", "2026-10-05 12:00:00", "2026-10-05 13:00:00", "2026-10-05 14:00:00"]:
        for a in auths:
            e = ent.get((a, va), {})
            fl = [e[fp][0] for fp in fam if fp in e]
            crow.append([va, a, len(fl), sum(has(x, "Running") for x in fl), sum(has(x, "Exit") for x in fl),
                         sum(has(x, "BadExit") for x in fl), sum(has(x, "MiddleOnly") for x in fl),
                         sum(has(x, "Valid") for x in fl), sum(has(x, "V2Dir") for x in fl)])
    with open(O("votes_consensus_20261005.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "authority", "family_relays_listed", "Running", "Exit", "BadExit", "MiddleOnly",
                    "Valid", "V2Dir"])
        w.writerows(crow)
    print("2026-10-05 family relays in votes (listed/Running/Exit/BadExit/MiddleOnly):")
    for va in sorted({r[0] for r in crow}):
        print("   ", va, " ".join("%s:%d/%d/%d/%d/%d" % (r[1][:4], r[2], r[3], r[4], r[5], r[6]) for r in crow if r[0] == va))


if __name__ == "__main__":
    main()
