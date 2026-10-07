#!/usr/bin/env python3
"""net_victims.py - victim census, attacker-policy transitions and waves (network-wide).

Victim = any relay that published a descriptor whose IPv4 exit policy summarizes (re-implemented
policy_summarize) to near-open or OUR_POLICY.

Outputs (net/):
  victims.csv                 one row per victim: identity, operator (exact contact), AS, first/last
                              attacker descriptor, how it got there, state at end of window
  attacker_transitions.csv    every descriptor-level class change into/out of {near-open, OUR_POLICY}
                              (and first descriptors that already carry one), with restart/reload
  waves_15min.csv             transitions chained with gaps <= 15 min: timing to the second,
                              operators, ASes, kinds, host order statistics
  waves_15min_events.csv      the events of each wave in time order
Prints the key numbers.
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (chain_bursts, epoch_ts, order_stats, ts_epoch, KNOWN_INFECTION,  # noqa: E402
                    log)

ATT = ("near-open", "OUR_POLICY")


def load_common(db):
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    contact["-"] = "(no contact line)"
    ipas = {r[0]: r[1:] for r in db.execute("SELECT ip, asn, as_name, org_name FROM ip_as")}
    vas = [r[0] for r in db.execute("SELECT va FROM consensus ORDER BY va")]
    return contact, ipas, vas


def asn_of(ipas, ip):
    r = ipas.get(ip)
    return ("AS" + r[0].replace("_", "/AS")) if r and r[0] else "unmapped"


def asname_of(ipas, ip):
    r = ipas.get(ip)
    return (r[2] or r[1]) if r else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    contact, ipas, vas = load_common(db)
    last_va = vas[-1]
    seeds = set()
    for line in open(args.seed):
        t = line.split("#")[0].strip().upper()
        if len(t) == 40:
            seeds.add(t)
    fam = seeds | {r[0] for r in db.execute(
        "SELECT DISTINCT d.fp FROM descriptor d LEFT JOIN contact c ON c.contact_h=d.contact_h "
        "WHERE lower(d.nickname) LIKE '%quetzal%' OR lower(c.text) LIKE '%quetzal%'")}
    victims = [r[0] for r in db.execute("SELECT fp FROM victim ORDER BY fp")]
    vset = set(victims)
    last_desc_e = db.execute("SELECT max(pub_epoch) FROM descriptor").fetchone()[0]

    # ---------------------------------------------------------------- transitions
    ev = []
    for r in db.execute("""SELECT fp, published, pub_epoch, prev_published, nickname, address, contact_h,
                             old_class, new_class, old_summary, new_summary, kind, new_h
                           FROM policy_event ORDER BY pub_epoch, fp"""):
        fp, pub, pe, ppub, nick, addr, ch, oc, nc, os_, ns, kind, nh = r
        if fp not in vset:
            continue
        o_att, n_att = oc in ATT, nc in ATT
        if kind == "first":
            if not n_att:
                continue
            direction = "into(first-descriptor)"
        elif not o_att and not n_att:
            continue  # change between two non-attacker classes
        elif oc == nc:
            continue  # attacker text changed but class did not
        elif n_att and not o_att:
            direction = "into"
        elif o_att and not n_att:
            direction = "out"
        else:
            direction = "between-attacker-classes"
        ev.append({"t": pe, "published": pub, "prev_published": ppub or "", "fp": fp, "nickname": nick,
                   "ip": addr, "operator": contact.get(ch, ch), "asn": asn_of(ipas, addr),
                   "as_name": asname_of(ipas, addr), "old_class": oc or "", "new_class": nc,
                   "kind": kind, "direction": direction, "family": int(fp in fam), "new_policy_h": nh})
    with open(os.path.join(args.out, "attacker_transitions.csv"), "w", newline="") as f:
        w = csv.writer(f)
        cols = ["published", "fp", "nickname", "ip", "asn", "as_name", "operator", "family", "old_class",
                "new_class", "direction", "kind", "prev_published", "new_policy_h"]
        w.writerow(cols)
        for e in ev:
            w.writerow([e[c] for c in cols])

    # ---------------------------------------------------------------- waves (<= 15 min)
    waves = chain_bursts(ev, 900, key=lambda e: e["t"])
    wrows, erows = [], []
    for i, wv in enumerate(waves, 1):
        hosts = []
        for e in wv:
            if e["ip"] not in hosts:
                hosts.append(e["ip"])
        st = order_stats(hosts)
        ops = collections.Counter(e["operator"] for e in wv)
        ases = collections.Counter(e["asn"] + " " + e["as_name"] for e in wv)
        kinds = collections.Counter(e["kind"] for e in wv)
        dirs = collections.Counter(e["direction"] + ":" + e["new_class"] for e in wv)
        wrows.append([i, wv[0]["published"], wv[-1]["published"], len(wv), len({e["fp"] for e in wv}),
                      len(hosts), sum(e["family"] for e in wv),
                      "; ".join("%s=%d" % kv for kv in dirs.most_common()),
                      "; ".join("%s=%d" % kv for kv in kinds.most_common()),
                      len(ops), " || ".join("%s [%d]" % (k[:90], v) for k, v in ops.most_common()),
                      "; ".join("%s=%d" % kv for kv in ases.most_common()),
                      st["inv_str"], st["inv_num"], st["inv_nodot"], st["pairs"], st["run_str"], st["run_num"],
                      " ".join(hosts)])
        for e in wv:
            erows.append([i, e["published"], e["fp"], e["nickname"], e["ip"], e["asn"], e["as_name"],
                          e["operator"][:120], e["family"], e["old_class"], e["new_class"], e["direction"],
                          e["kind"]])
    with open(os.path.join(args.out, "waves_15min.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wave", "start", "end", "events", "relays", "hosts", "family_events", "directions",
                    "kinds", "n_operators", "operators", "ases", "inv_str", "inv_num", "inv_nodot", "pairs",
                    "longest_run_str", "longest_run_num", "host_order"])
        w.writerows(wrows)
    with open(os.path.join(args.out, "waves_15min_events.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wave", "published", "fp", "nickname", "ip", "asn", "as_name", "operator", "family",
                    "old_class", "new_class", "direction", "kind"])
        w.writerows(erows)

    # ---------------------------------------------------------------- victim census
    rows = []
    for fp in victims:
        ds = db.execute("""SELECT d.published, d.pub_epoch, d.nickname, d.address, d.contact_h, p.class,
                             p.summary, d.platform, d.policy_h FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                           WHERE d.fp=? ORDER BY d.pub_epoch""", (fp,)).fetchall()
        att = [d for d in ds if d[5] in ATT]
        first_any = ds[0]
        pre = [d for d in ds if d[1] < att[0][1]]
        prior_class = pre[-1][5] if pre else "(none: attacker policy from first descriptor in window)"
        long_standing = int(not pre)
        last = ds[-1]
        ivs = db.execute("SELECT start_va, end_va, flags, policy FROM cons_interval WHERE fp=? ORDER BY start_va",
                         (fp,)).fetchall()
        end_va = ivs[-1][1] if ivs else ""
        in_final = int(end_va == last_va)
        last_flags = ivs[-1][2] if ivs else ""
        last_p = ivs[-1][3] if ivs else ""
        ever_badexit = int(any("BadExit" in iv[2].split() for iv in ivs))
        ever_mo = int(any("MiddleOnly" in iv[2].split() for iv in ivs))
        first_bad = next((iv[0] for iv in ivs if "BadExit" in iv[2].split()), "")
        first_mo = next((iv[0] for iv in ivs if "MiddleOnly" in iv[2].split()), "")
        still = int(last[5] in ATT)
        rows.append([fp, last[2], last[3], asn_of(ipas, last[3]), asname_of(ipas, last[3]),
                     contact.get(last[4], last[4]), int(fp in fam), first_any[0], prior_class, att[0][0],
                     att[0][5], att[-1][0], len(att), len({d[8] for d in att}), long_standing,
                     int(att[0][0] < "2026-10-01"), last[0], last[5], still, end_va, in_final, last_flags,
                     last_p, ever_badexit, first_bad, ever_mo, first_mo, last[7]])
    hdr = ["fp", "nickname", "ip", "asn", "as_name", "operator", "family", "first_desc_in_window",
           "class_before_first_attacker_desc", "first_attacker_desc", "first_attacker_class",
           "last_attacker_desc", "n_attacker_descs", "n_attacker_policy_texts", "attacker_policy_from_first_desc",
           "first_attacker_before_oct1", "last_desc", "last_desc_class", "last_desc_is_attacker",
           "last_consensus_va", "in_final_consensus", "last_flags", "last_p_line", "ever_badexit",
           "first_badexit_va", "ever_middleonly", "first_middleonly_va", "platform"]
    with open(os.path.join(args.out, "victims.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)

    # ---------------------------------------------------------------- print summary
    print("last consensus scanned:", last_va, "; last descriptor published:", epoch_ts(last_desc_e))
    print("victims (relays with >=1 attacker-class descriptor):", len(victims))
    print("  by first attacker class:", collections.Counter(r[10] for r in rows))
    print("  attacker policy from first descriptor in window (long-standing or new relay):",
          sum(r[14] for r in rows))
    print("  first attacker descriptor before 2026-10-01:", sum(r[15] for r in rows))
    print("  family members among victims:", sum(r[6] for r in rows))
    print("  last descriptor still attacker-class:", sum(r[18] for r in rows))
    print("  ever BadExit:", sum(r[23] for r in rows), " ever MiddleOnly:", sum(r[25] for r in rows))
    print("  by AS:", collections.Counter(r[3] + " " + r[4] for r in rows).most_common(15))
    print("  operators:", len({r[5] for r in rows}))
    for k, v in collections.Counter(r[5] for r in rows).most_common(30):
        print("     %3d  %s" % (v, k[:150]))
    att_all = db.execute("""SELECT d.published, d.fp, d.nickname, d.address, p.class FROM descriptor d
                            JOIN policy p ON p.policy_h=d.policy_h WHERE p.class IN ('near-open','OUR_POLICY')
                            ORDER BY d.pub_epoch LIMIT 5""").fetchall()
    print("earliest attacker-class descriptors anywhere:", att_all)
    for c in ATT:
        print("earliest", c, db.execute("""SELECT d.published, d.fp, d.nickname, d.address FROM descriptor d
                            JOIN policy p ON p.policy_h=d.policy_h WHERE p.class=? ORDER BY d.pub_epoch LIMIT 1""",
                                         (c,)).fetchone())
    print("transitions:", len(ev), collections.Counter(e["direction"] for e in ev))
    print("waves (<=15 min):", len(waves))
    for r in wrows:
        if r[3] >= 2 or r[1] >= "2026-09-25":
            print("  wave %d %s .. %s events=%d relays=%d hosts=%d fam=%d ops=%d %s | %s | %s | inv str/num/nodot %d/%d/%d of %d"
                  % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[9], r[7], r[8], r[11][:160], r[12], r[13],
                     r[14], r[15]))


if __name__ == "__main__":
    main()
