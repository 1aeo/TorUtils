#!/usr/bin/env python3
"""email_status_now.py - status of the 377 affected relays at the newest public data, from four sources, for
item 15 of EMAIL_DRAFT.txt. Also the "never flagged" checks over every October vote.

Sources:
  * consensus: newest data_recent/consensuses/* (listed or not, flags, p line);
  * votes: net/votes_recent_victims.csv + net/votes_recent_meta.csv (scripts/email_votes_recent.py, every vote
    10-07 02:00 .. newest) and net/netdb.sqlite vote_entry (10-01 00:00 .. 10-07 01:00). A vote "r" line carries
    the publication time of the descriptor the authority holds; the "s" line says whether that authority
    found the relay reachable ("Running");
  * descriptors: net/netdb.sqlite descriptor + every data_recent/server-descriptors/* file (CollecTor's
    descriptor files lag the votes by a few hours);
  * Onionoo: newest onionoo_YYYYMMDDTHH/details.json (cross-check only: Onionoo's running/last_seen come from the
    consensus, so a relay left out of the consensus shows as not running whatever it does).

Definitions:
  * window = the 24 h before the newest consensus valid-after;
  * "publishing" = newest descriptor (CollecTor or vote r line) published inside the window;
  * "reachable" = at least one authority votes it Running in the newest vote round.

Usage: python3 -I scripts/email_status_now.py > net/email_status_now.log
"""
import collections
import csv
import datetime as dt
import glob
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY, summarize_policy  # noqa: E402
from build_netdb import parse_descriptor, parse_consensus  # noqa: E402
from email_current_status import split_descriptors  # noqa: E402

ROOT = os.path.dirname(HERE)
CLS = {OUR_POLICY: "A", NEAR_OPEN: "B"}
FLAG9 = "9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76"


def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def main():
    vic = {r["fp"]: r for r in csv.DictReader(open(os.path.join(ROOT, "net/victims.csv")))}
    fam = {f for f, r in vic.items() if r["family"] == "1"}
    db = sqlite3.connect(os.path.join(ROOT, "net/netdb.sqlite"))

    # ------------------------------------------------------------ newest consensus
    cpath = sorted(glob.glob(os.path.join(ROOT, "data_recent/consensuses/*-consensus")))[-1]
    va_now, entries = parse_consensus(open(cpath, "rb").read())
    # entry: [nick, fp, digest, published, ip, orport, dirport, flags, version, bw, p line, a line]
    listed = {e[1]: e for e in entries if e[1] in vic}
    cut = (ts(va_now) - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    print("newest consensus:", va_now, " window start:", cut, " relays in it:", len(entries))
    print("affected relays listed now:", len(listed))
    for fp, e in listed.items():
        print("   ", fp, vic[fp]["nickname"], "flags:", e[7], "p:", e[10])

    # ------------------------------------------------------------ votes
    meta = list(csv.DictReader(open(os.path.join(ROOT, "net/votes_recent_meta.csv"))))
    rounds = sorted({m["valid_after"] for m in meta})
    last_round = rounds[-1]
    vr = list(csv.DictReader(open(os.path.join(ROOT, "net/votes_recent_victims.csv"))))
    now_votes = collections.defaultdict(list)
    for r in vr:
        if r["valid_after"] == last_round:
            now_votes[r["fp"]].append(r)
    print("recent vote rounds:", len(rounds), rounds[0], "..", last_round,
          " votes in last round:", sum(1 for m in meta if m["valid_after"] == last_round))

    # never voted BadExit / MiddleOnly in any October vote (archive + recent)
    flagged_vote = collections.defaultdict(set)
    for fp, auth, flags in db.execute("SELECT fp, auth, flags FROM vote_entry WHERE va >= '2026-10-01'"):
        f = flags.split()
        if fp in vic and ("BadExit" in f or "MiddleOnly" in f):
            flagged_vote[fp].add(auth)
    for r in vr:
        f = r["flags"].split()
        if "BadExit" in f or "MiddleOnly" in f:
            flagged_vote[r["fp"]].add(r["authority"])
    never = sorted(fp for fp in vic if fp not in flagged_vote)
    nfirst = db.execute("SELECT min(va), max(va), count(DISTINCT va) FROM vote").fetchone()
    print(f"\n== never voted BadExit or MiddleOnly by any authority, votes {nfirst[0]} .. {last_round} "
          f"({nfirst[2]} archive rounds + {len(rounds)} recent rounds): {len(never)} "
          f"(Quetzalcoatl {sum(f in fam for f in never)})")
    # the previous list (archive votes only)
    ff = list(csv.DictReader(open(os.path.join(ROOT, "net/votes_victim_first_flag.csv"))))
    old_never = {r["fp"] for r in ff if not any(r[k] for k in r if k.endswith(("_BadExit", "_MiddleOnly")))}
    print("   archive-only list:", len(old_never), " newly flagged since 10-07 02:00:",
          sorted((f, vic[f]["nickname"], sorted(flagged_vote[f])) for f in old_never - set(never)))

    # 14 never-flagged usable A/B exits of 10-04 21:00 .. 10-05 15:00
    vas = [r[0] for r in db.execute("SELECT va FROM consensus WHERE va BETWEEN '2026-10-04 21:00:00' "
                                     "AND '2026-10-05 15:00:00' ORDER BY va")]
    us = set()
    for va in vas:
        for fp, flags, pol in db.execute("SELECT fp, flags, policy FROM cons_entry WHERE va=?", (va,)):
            f = flags.split()
            if fp in vic and pol in CLS and "Exit" in f and "BadExit" not in f and fp in old_never:
                us.add(fp)
    print(f"   the {len(us)} unflagged usable A/B exits of 10-04 21:00..10-05 15:00: still never voted "
          f"BadExit/MiddleOnly as of {last_round}: {sum(f in never for f in us)}; first flag vote since: "
          f"{sorted((vic[f]['nickname'], min(r['valid_after'] for r in vr if r['fp'] == f and ('BadExit' in r['flags'].split() or 'MiddleOnly' in r['flags'].split()))) for f in us if f not in never)}")

    # ------------------------------------------------------------ descriptors
    newest = {}
    for fp, pub, up, txt in db.execute("""SELECT d.fp, d.published, d.uptime, p.text FROM descriptor d
                                          JOIN policy p ON p.policy_h=d.policy_h"""):
        if fp in vic and (fp not in newest or pub > newest[fp][0]):
            newest[fp] = (pub, up, txt, "db")
    for path in sorted(glob.glob(os.path.join(ROOT, "data_recent/server-descriptors/*"))):
        for d in split_descriptors(open(path, "rb").read()):
            p = parse_descriptor(d)
            fp = p.get("fingerprint")
            if fp in vic and (fp not in newest or p["published"] > newest[fp][0]):
                newest[fp] = (p["published"], p.get("uptime"), "\n".join(p["policy"]), os.path.basename(path))
    last_file = sorted(glob.glob(os.path.join(ROOT, "data_recent/server-descriptors/*")))[-1]
    print("\nnewest CollecTor descriptor file:", os.path.basename(last_file))

    def vote_newest(fp):
        rr = [r for r in vr if r["fp"] == fp]
        return max((r["desc_published"] for r in rr), default="")

    # ------------------------------------------------------------ Onionoo
    oopath = sorted(glob.glob(os.path.join(ROOT, "onionoo_2026*T*/details.json")))[-1]  # newest snapshot
    oo = json.load(open(oopath))
    oor = {r["fingerprint"]: r for r in oo["relays"]}
    print("Onionoo relays_published:", oo["relays_published"])

    # ------------------------------------------------------------ classify
    rows = []
    for fp in sorted(vic):
        cpub, cup, ctxt, csrc = newest.get(fp, ("", None, "", ""))
        vpub = vote_newest(fp)
        nv = now_votes.get(fp, [])
        pub = max(cpub, vpub)
        if pub == vpub and vpub > cpub:
            pcls = CLS.get(nv[0]["p"] if nv else
                           [r for r in vr if r["fp"] == fp and r["desc_published"] == vpub][0]["p"], "other")
        else:
            pcls = CLS.get(summarize_policy(ctxt.split("\n")) if ctxt else "", "other")
        start = ""
        if cpub and cup is not None:
            start = (ts(cpub) - dt.timedelta(seconds=int(cup))).strftime("%Y-%m-%d %H:%M:%S")
        o = oor.get(fp, {})
        st = "listed" if fp in listed else ("publishing" if pub >= cut else "silent")
        rows.append(dict(fp=fp, nickname=vic[fp]["nickname"], family=vic[fp]["family"], asn=vic[fp]["asn"],
                         status=st, newest_published=pub, newest_source="vote" if vpub > cpub else csrc,
                         newest_class=pcls, collector_newest=cpub, collector_tor_start=start,
                         votes_listing=len(nv), votes_running=sum("Running" in r["flags"].split() for r in nv),
                         votes_exit=sum("Exit" in r["flags"].split() for r in nv),
                         votes_flagged=sum(("BadExit" in r["flags"].split() or "MiddleOnly" in r["flags"].split())
                                           for r in nv),
                         listing_auths=" ".join(sorted(r["authority"] for r in nv)),
                         never_flag_vote=int(fp in never),
                         onionoo_present=int(bool(o)), onionoo_running=o.get("running", ""),
                         onionoo_last_seen=o.get("last_seen", ""),
                         onionoo_last_restarted=o.get("last_restarted", ""),
                         onionoo_flags=" ".join(o.get("flags", []) or [])))
    with open(os.path.join(ROOT, "net/email_status_now.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def summary(sel, label):
        print(f"\n== {label}: {len(sel)} (Quetzalcoatl {sum(r['family'] == '1' for r in sel)}, FranTech "
              f"{sum(r['asn'] == 'AS53667' for r in sel)})")
        if not sel:
            return
        print("   newest descriptor:", min(r["newest_published"] for r in sel), "..",
              max(r["newest_published"] for r in sel))
        print("   newest policy:", dict(collections.Counter(r["newest_class"] for r in sel)))
        print("   authorities listing in", last_round, ":",
              dict(sorted(collections.Counter(r["votes_listing"] for r in sel).items())),
              " voting Running:", dict(sorted(collections.Counter(r["votes_running"] for r in sel).items())))
        print("   listing authorities:", dict(collections.Counter(a for r in sel for a in r["listing_auths"].split())))
        print("   Onionoo: present", sum(r["onionoo_present"] for r in sel), " running",
              dict(collections.Counter(str(r["onionoo_running"]) for r in sel)),
              " last_seen", min((r["onionoo_last_seen"] for r in sel if r["onionoo_last_seen"]), default=""), "..",
              max((r["onionoo_last_seen"] for r in sel if r["onionoo_last_seen"]), default=""))

    summary([r for r in rows if r["status"] == "listed"], "listed in " + va_now)
    pubr = [r for r in rows if r["status"] == "publishing"]
    summary(pubr, f"not listed, descriptor published {cut} .. {va_now}")
    summary([r for r in pubr if r["newest_class"] in ("A", "B")], "  of which newest policy A or B")
    summary([r for r in pubr if r["newest_class"] == "other"], "  of which another policy")
    summary([r for r in pubr if r["votes_running"] > 0], "  of which voted Running by >= 1 authority")
    summary([r for r in pubr if r["votes_running"] == 0], "  of which voted Running by no authority")
    summary([r for r in rows if r["status"] == "silent"], f"silent: no descriptor since {cut}")
    sil = [r for r in rows if r["status"] == "silent"]
    print("   silent: newest descriptor", max(r["newest_published"] for r in sil))
    for r in rows:
        if r["status"] == "publishing" and (r["votes_running"] == 0 or r["family"] == "1"):
            print("   publishing, no Running vote or Quetzalcoatl:", {k: r[k] for k in (
                "fp", "nickname", "family", "newest_published", "newest_source", "newest_class",
                "collector_newest", "collector_tor_start", "votes_listing", "votes_running", "listing_auths",
                "onionoo_running", "onionoo_last_seen", "onionoo_last_restarted")})
    nv_rows = [r for r in rows if r["never_flag_vote"]]
    summary(nv_rows, "never voted BadExit/MiddleOnly")
    summary([r for r in nv_rows if r["status"] == "publishing"], "  never flagged and publishing")

    # 07DCECDF over the recent votes
    fp = "07DCECDF04BE5D470C615C8E1CCF086F74FC8CA6"
    hist = [r for r in vr if r["fp"] == fp]
    print("\n== 07DCECDF in recent votes:", len(hist), "entries,", len({r['valid_after'] for r in hist}), "rounds",
          min((r["valid_after"] for r in hist), default=""), "..", max((r["valid_after"] for r in hist), default=""))
    print("   descriptor publication times seen:", sorted({r["desc_published"] for r in hist}))
    print("   authorities:", dict(collections.Counter(r["authority"] for r in hist)),
          " Running votes:", sum("Running" in r["flags"].split() for r in hist))
    print("   CollecTor newest:", newest.get(fp, ("",))[0], " Onionoo:",
          {k: oor.get(fp, {}).get(k) for k in ("running", "last_seen", "last_restarted", "flags")})

    # 9CDB4020 now
    e = listed.get(FLAG9)
    print("\n== 9CDB4020 now:", e and ("flags: " + e[7] + " | p: " + e[10]))
    # cons_entry starts 09-24; cons_interval covers 05-01 onward
    hist = db.execute("SELECT min(start_va) FROM cons_interval WHERE fp=? AND (' '||flags||' ') LIKE '% BadExit %'",
                      (FLAG9,)).fetchone()[0]
    hist2 = db.execute("SELECT min(start_va) FROM cons_interval WHERE fp=? AND (' '||flags||' ') LIKE "
                       "'% MiddleOnly %'", (FLAG9,)).fetchone()[0]
    print("   first consensus with BadExit:", hist, " with MiddleOnly:", hist2)


if __name__ == "__main__":
    main()
