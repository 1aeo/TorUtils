#!/usr/bin/env python3
"""email_followup_answers.py - numbers for the second revision of the tor-relays reply (EMAIL_DRAFT.txt).

Answers, from public data only:
  The "now" window is the 24 h before the latest consensus in data_recent/.
  A. Latest authority votes (data_recent/votes/, one vote round from CollecTor recent/): for every one of
     the 377 affected relays, how many of the 9 authorities list it, grouped by current status from
     net/email_current_status.csv (publishing A/B, publishing another policy, silent). A relay's newest
     descriptor is the newer of the CollecTor files and the "r" line publication time in the latest votes
     (CollecTor's descriptor files lag the votes by a few hours).
  B. The relays whose newest descriptor has neither A nor B: is the newest policy text the exact
     pre-incident text (last descriptor before the first A/B descriptor), the same after
     common.normalize_policy, or different?
  C. The 57 affected relays that no authority ever voted BadExit or MiddleOnly for
     (net/votes_victim_first_flag.csv): which policy (A, B or both), Quetzalcoatl or not, and current status.
  D. The consensus of 2026-10-05 12:00:00: affected relays listed with an A/B p line, how many authorities
     listed each, BadExit / MiddleOnly vote counts, and which of them had the Exit flag.

Policy A = common.OUR_POLICY summary, Policy B = common.NEAR_OPEN summary.
Usage: python3 -I scripts/email_followup_answers.py > net/email_followup_answers.log
"""
import collections
import datetime as dt
import csv
import glob
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY, summarize_policy, normalize_policy, b64_to_hex  # noqa: E402
from build_netdb import parse_descriptor  # noqa: E402
from email_current_status import split_descriptors  # noqa: E402


ROOT = os.path.dirname(HERE)
CLS = {OUR_POLICY: "A", NEAR_OPEN: "B"}


def read_votes(paths):
    """{auth: {'va', 'known', 'entries': {fp: [flags set, p line, descriptor published]}}} for one vote round."""
    out = {}
    for path in paths:
        data = open(path, "rb").read()
        va = auth = kf = None
        ent = {}
        cur = None
        for raw in data.split(b"\n"):
            c = raw[:2]
            if c == b"r ":
                p = raw.split(b" ")
                cur = b64_to_hex(p[2].decode())
                ent[cur] = [set(), "", (p[4] + b" " + p[5]).decode()]
            elif cur is not None and c == b"s ":
                ent[cur][0] = set(raw[2:].decode().split())
            elif cur is not None and c == b"p ":
                ent[cur][1] = raw[2:].decode().strip()
            elif raw.startswith(b"valid-after "):
                va = raw[12:].decode().strip()
            elif raw.startswith(b"known-flags "):
                kf = set(raw[12:].decode().split())
            elif raw.startswith(b"dir-source ") and auth is None:
                auth = raw.split()[1].decode()
            elif raw.startswith(b"directory-footer"):
                break
        out[auth] = {"va": va, "known": kf, "entries": ent}
    return out


def main():
    vic = {r["fp"]: r for r in csv.DictReader(open(os.path.join(ROOT, "net/victims.csv")))}
    st = {r["fp"]: r for r in csv.DictReader(open(os.path.join(ROOT, "net/email_current_status.csv")))}
    db = sqlite3.connect(os.path.join(ROOT, "net/netdb.sqlite"))

    # newest descriptor in the recent files, per affected relay (full policy text)
    newest = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "data_recent/server-descriptors/*"))):
        for d in split_descriptors(open(path, "rb").read()):
            p = parse_descriptor(d)
            fp = p.get("fingerprint")
            if fp in vic and (fp not in newest or p["published"] > newest[fp]["published"]):
                newest[fp] = p
    newest_desc_time = max(p["published"] for p in newest.values())
    print("newest descriptor of an affected relay in data_recent:", newest_desc_time)


    def newest_any(fp):
        """(published, is A/B) of the newest descriptor seen in CollecTor files or in the latest votes."""
        s = st[fp]
        best = (s["last_desc_published"], s["last_desc_class"] in ("near-open", "OUR_POLICY"))
        for v in votes.values():
            e = v["entries"].get(fp)
            if e and e[2] > best[0]:
                best = (e[2], e[1] in CLS)
        return best

    def status(fp):
        if st[fp]["in_latest_consensus"] == "1":
            return "listed"
        pub, att = newest_any(fp)
        if pub >= CUT:
            return "publishing " + ("A/B" if att else "other")
        return "silent"

    # 24 h window ending at the latest consensus in data_recent/ (not at the newest descriptor, which can
    # carry a relay's skewed clock)
    latest_va = sorted(glob.glob(os.path.join(ROOT, "data_recent/consensuses/*-consensus")))[-1]
    latest_va = os.path.basename(latest_va)[:19]
    latest_va = latest_va[:10] + " " + latest_va[11:].replace("-", ":")
    CUT = dt.datetime.strftime(dt.datetime.strptime(latest_va, "%Y-%m-%d %H:%M:%S") - dt.timedelta(hours=24),
                               "%Y-%m-%d %H:%M:%S")
    print("latest consensus:", latest_va, " 24 h cutoff (>=):", CUT)
    vpaths = sorted(glob.glob(os.path.join(ROOT, "data_recent/votes/*-vote-*")))
    votes = read_votes(vpaths)
    newer = [fp for fp in vic if newest_any(fp)[0] > st[fp]["last_desc_published"]]
    print("affected relays whose newest descriptor is in the votes but not (yet) in the CollecTor files:",
          len(newer))
    for fp in newer:
        if st[fp]["last_desc_published"] < CUT:
            print(f"   status changes: {fp} {vic[fp]['nickname']} fam={vic[fp]['family']} {vic[fp]['ip']} "
                  f"{vic[fp]['asn']} CollecTor newest {st[fp]['last_desc_published']}, vote newest "
                  f"{newest_any(fp)[0]} A/B={newest_any(fp)[1]}, listed by "
                  f"{sorted(a for a, v in votes.items() if fp in v['entries'])}")
    sil = [fp for fp in vic if status(fp) == "silent"]
    print("silent relays (both sources): newest descriptor", max(newest_any(fp)[0] for fp in sil))

    # ------------------------------------------------------------------ A. latest votes
    vas = {v["va"] for v in votes.values()}
    print("\n== A. vote round", sorted(vas), "authorities:", sorted(votes))
    nlist = {fp: sum(1 for v in votes.values() if fp in v["entries"]) for fp in vic}
    groups = collections.defaultdict(list)
    for fp in vic:
        groups[status(fp)].append(fp)
    for g, fps in sorted(groups.items()):
        dist = collections.Counter(nlist[fp] for fp in fps)
        print(f"   {g}: {len(fps)} relays; listed by n of {len(votes)} authorities: {dict(sorted(dist.items()))}")
        if g.startswith("publishing A/B"):
            by_auth = collections.Counter(a for fp in fps for a, v in votes.items() if fp in v["entries"])
            print("      listing authorities:", dict(by_auth))
            fl = collections.Counter()
            for fp in fps:
                for a, v in votes.items():
                    if fp in v["entries"]:
                        for f in ("Exit", "BadExit", "MiddleOnly", "Running", "Valid"):
                            if f in v["entries"][fp][0]:
                                fl[f] += 1
            print("      flag votes on them (sum over authorities):", dict(fl))
            print("      family:", sum(vic[fp]["family"] == "1" for fp in fps),
                  " FranTech:", sum(vic[fp]["asn"] == "AS53667" for fp in fps))

    # ------------------------------------------------------------------ B. other-policy relays
    print("\n== B. affected relays whose newest descriptor is neither A nor B")
    cnt = collections.Counter()
    for fp in sorted(groups.get("publishing other", []) + groups.get("listed", [])):
        first_att = vic[fp]["first_attacker_desc"]
        row = db.execute("""SELECT p.text, d.published FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                            WHERE d.fp=? AND d.published < ? ORDER BY d.pub_epoch DESC LIMIT 1""",
                         (fp, first_att)).fetchone()
        new = newest.get(fp)
        new_txt = "\n".join(new["policy"]) if new else None
        if row is None:
            kind = "no pre-incident descriptor (new key)"
        elif new_txt == row[0]:
            kind = "exact pre-incident text"
        elif normalize_policy(new_txt.split("\n"), {new.get("address")}) == \
                normalize_policy(row[0].split("\n"), {new.get("address")}):
            kind = "same as pre-incident after normalization"
        else:
            kind = "different from pre-incident"
        cnt[kind] += 1
        print(f"   {fp} {vic[fp]['nickname']:<20} {vic[fp]['asn']:<9} status={status(fp):<16} "
              f"newest={new['published'] if new else '-'} {summarize_policy(new['policy']) if new else ''!s:.40} | {kind}")
    print("   totals:", dict(cnt))

    # ------------------------------------------------------------------ C. never flagged in any vote
    print("\n== C. affected relays never voted BadExit or MiddleOnly by any authority (Oct votes)")
    ff = list(csv.DictReader(open(os.path.join(ROOT, "net/votes_victim_first_flag.csv"))))
    never = [r["fp"] for r in ff if not any(r[k] for k in r if k.endswith(("_BadExit", "_MiddleOnly")))]
    pol = collections.defaultdict(set)
    for r in csv.DictReader(open(os.path.join(ROOT, "net/attacker_transitions.csv"))):
        if r["direction"] == "into" and r["new_class"] in ("near-open", "OUR_POLICY"):
            pol[r["fp"]].add("A" if r["new_class"] == "OUR_POLICY" else "B")
    # also count any descriptor with an A/B summary (covers first descriptors of new keys)
    for fp in never:
        for (s,) in db.execute("""SELECT DISTINCT p.summary FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                                  WHERE d.fp=?""", (fp,)):
            if s in CLS:
                pol[fp].add(CLS[s])
        new = newest.get(fp)
        if new and summarize_policy(new["policy"]) in CLS:
            pol[fp].add(CLS[summarize_policy(new["policy"])])
    print("   count:", len(never), " Quetzalcoatl:", sum(vic[fp]["family"] == "1" for fp in never))
    print("   policy used:", dict(collections.Counter("+".join(sorted(pol[fp])) for fp in never)))
    print("   policy used, Quetzalcoatl:",
          dict(collections.Counter("+".join(sorted(pol[fp])) for fp in never if vic[fp]["family"] == "1")))
    print("   current status:", dict(collections.Counter(status(fp) for fp in never)))
    print("   ever listed in a consensus with an A/B p line:",
          sum(1 for fp in never if db.execute(
              "SELECT 1 FROM cons_entry WHERE fp=? AND policy IN (?,?) LIMIT 1", (fp, NEAR_OPEN, OUR_POLICY)).fetchone()))
    print("   ever had Exit (no BadExit) with an A/B p line in a consensus:",
          sum(1 for fp in never if db.execute(
              "SELECT 1 FROM cons_entry WHERE fp=? AND policy IN (?,?) AND (' '||flags||' ') LIKE '% Exit %' "
              "AND (' '||flags||' ') NOT LIKE '% BadExit %' LIMIT 1", (fp, NEAR_OPEN, OUR_POLICY)).fetchone()))
    for fp in sorted(never, key=lambda f: newest_any(f)[0], reverse=True):
        if status(fp) != "silent":
            s = st[fp]
            print(f"   not silent: {fp} {vic[fp]['nickname']:<18} fam={vic[fp]['family']} {vic[fp]['asn']:<9} "
                  f"policy={'+'.join(sorted(pol[fp]))} status={status(fp)} newest={newest_any(fp)[0]} "
                  f"class={s['last_desc_class']} listed_by={nlist[fp]}/9")
    last_silent = max(newest_any(fp)[0] for fp in never if status(fp) == "silent")
    print("   newest descriptor among the silent ones:", last_silent)

    # ------------------------------------------------------------------ D. 2026-10-05 12:00
    print("\n== D. consensus 2026-10-05 11:00 and 12:00, affected relays with an A/B p line")
    for va in ("2026-10-05 11:00:00", "2026-10-05 12:00:00"):
        rows = db.execute("SELECT fp, flags, policy FROM cons_entry WHERE va=? AND policy IN (?,?)",
                          (va, NEAR_OPEN, OUR_POLICY)).fetchall()
        auths = [a for (a,) in db.execute("SELECT auth FROM vote WHERE va=?", (va,))]
        known_bad = [a for (a,) in db.execute("SELECT auth FROM vote WHERE va=? AND has_badexit_flag=1", (va,))]
        lst = collections.Counter()
        bad = collections.Counter()
        mid = collections.Counter()
        for a, fp, fl in db.execute("SELECT auth, fp, flags FROM vote_entry WHERE va=?", (va,)):
            if fp in {r[0] for r in rows}:
                lst[fp] += 1
                bad[fp] += "BadExit" in fl.split()
                mid[fp] += "MiddleOnly" in fl.split()
        listing = collections.Counter(a for a, fp, fl in db.execute("SELECT auth, fp, flags FROM vote_entry WHERE va=?", (va,))
                                      if fp in {r[0] for r in rows})
        print(f"   {va}: {len(rows)} listed with A/B (family {sum(vic.get(r[0], {}).get('family') == '1' for r in rows)});"
              f" votes {len(auths)}; BadExit known by {len(known_bad)} {sorted(known_bad)}")
        print("      authorities listing them:", dict(listing))
        print("      listed by n authorities:", dict(collections.Counter(lst[r[0]] for r in rows)))
        print("      BadExit votes:", dict(collections.Counter(bad[r[0]] for r in rows)),
              " MiddleOnly votes:", dict(collections.Counter(mid[r[0]] for r in rows)))
        print("      consensus BadExit:", sum("BadExit" in r[1].split() for r in rows),
              " MiddleOnly:", sum("MiddleOnly" in r[1].split() for r in rows),
              " Exit:", sum("Exit" in r[1].split() for r in rows))
        ex = [r[0] for r in rows if "Exit" in r[1].split()]
        print("      with Exit:", len(ex), " family:", sum(vic[f]["family"] == "1" for f in ex),
              " never voted BadExit/MiddleOnly:", sum(f in never for f in ex))
        if va.endswith("12:00:00"):
            for f in ex:
                print(f"         {f} {vic[f]['nickname']:<18} {vic[f]['asn']}")
            noexit = [r for r in rows if "Exit" not in r[1].split()]
            print("      without Exit:", len(noexit), " family:", sum(vic[r[0]]["family"] == "1" for r in noexit))


if __name__ == "__main__":
    main()
