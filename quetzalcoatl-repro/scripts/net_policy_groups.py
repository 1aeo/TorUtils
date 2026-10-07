#!/usr/bin/env python3
"""net_policy_groups.py - identical exit-policy changes across operators (network-wide, whole window).

Every descriptor-level policy-text change (policy_event, kinds restart/reload) is normalized by removing
the relay's own-IP /32 lines (router address and IPv4 or-addresses) and tor's private-net lines.
Changes whose normalized text did not change (e.g. an IP change) are dropped.
Events are grouped by normalized NEW policy and chained in time with gaps <= 60 minutes.
A group is reported when it has >= 3 relays from >= 2 operators (operator = exact contact string).

Outputs (net/):
  policy_change_groups.csv          all qualifying groups (whole window), with class, span, operators, ASes
  policy_change_groups_events.csv   their events
  policy_change_groups_baseline.csv count of qualifying groups per month (all / exit-policy / attacker)
"""
import argparse
import collections
import csv
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (chain_bursts, classify_summary, normalize_policy, summarize_policy,  # noqa: E402
                    KNOWN_INFECTION, log)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    contact["-"] = "(no contact line)"
    ptext = {}
    ipas = {r[0]: r[1:] for r in db.execute("SELECT ip, asn, as_name FROM ip_as")}
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    q = db.execute("""SELECT e.fp, e.published, e.pub_epoch, e.nickname, e.address, e.contact_h, e.old_h, e.new_h,
                             e.new_summary, e.kind, d.or_addresses, pd.or_addresses, pd.address
                      FROM policy_event e
                      JOIN descriptor d ON d.fp=e.fp AND d.published=e.published AND d.policy_h=e.new_h
                      LEFT JOIN descriptor pd ON pd.fp=e.fp AND pd.published=e.prev_published AND pd.policy_h=e.old_h
                      WHERE e.kind != 'first' ORDER BY e.pub_epoch""")
    norm_cache = {}
    ev = []
    n_raw = n_same = 0
    seen = set()

    def norm(h, own):
        k = (h, own)
        if k not in norm_cache:
            if h not in ptext:
                ptext[h] = db.execute("SELECT text FROM policy WHERE policy_h=?", (h,)).fetchone()[0]
            lines = ptext[h].split("\n") if ptext[h] else []
            norm_cache[k] = normalize_policy(lines, set(own))
        return norm_cache[k]

    for fp, pub, pe, nick, addr, ch, oh, nh, ns, kind, ora, pora, paddr in q:
        k = (fp, pub, nh)
        if k in seen:
            continue
        seen.add(k)
        n_raw += 1
        own_new = tuple(sorted({addr} | {x.rsplit(":", 1)[0] for x in (ora or "").split() if not x.startswith("[")}))
        own_old = tuple(sorted({paddr or addr} | {x.rsplit(":", 1)[0] for x in (pora or "").split()
                                                  if not x.startswith("[")}))
        nn = norm(nh, own_new)
        no = norm(oh, own_old) if oh else None
        if nn == no:
            n_same += 1
            continue
        nhash = hashlib.sha1(nn.encode()).hexdigest()[:12]
        ev.append((pe, pub, fp, nick, addr, contact.get(ch, ch), nhash, ns, classify_summary(ns), kind,
                   nn.count("\n") + 1 if nn else 0))
    log("policy changes: %d, normalized-identical (dropped): %d, kept: %d" % (n_raw, n_same, len(ev)))
    by_pol = collections.defaultdict(list)
    for e in ev:
        by_pol[e[6]].append(e)
    groups = []
    for h, es in by_pol.items():
        es.sort()
        for g in chain_bursts(es, 3600, key=lambda e: e[0]):
            relays = {e[2] for e in g}
            ops = {e[5] for e in g}
            if len(relays) >= 3 and len(ops) >= 2:
                groups.append(g)
    groups.sort(key=lambda g: g[0][0])
    with open(os.path.join(args.out, "policy_change_groups.csv"), "w", newline="") as f, \
            open(os.path.join(args.out, "policy_change_groups_events.csv"), "w", newline="") as f2:
        w, w2 = csv.writer(f), csv.writer(f2)
        w.writerow(["group", "start", "end", "span_min", "norm_policy", "summary", "class", "n_lines", "relays",
                    "hosts", "operators", "victim_relays", "kinds", "before_known_infection", "operator_list",
                    "ases"])
        w2.writerow(["group", "published", "fp", "nickname", "ip", "asn", "operator", "kind", "victim"])
        for i, g in enumerate(groups, 1):
            ops = collections.Counter(e[5] for e in g)
            ases = collections.Counter(("AS" + ipas[e[4]][0] if e[4] in ipas and ipas[e[4]][0] else "?")
                                       for e in g)
            w.writerow([i, g[0][1], g[-1][1], round((g[-1][0] - g[0][0]) / 60, 1), g[0][6], g[0][7], g[0][8],
                        g[0][10], len({e[2] for e in g}), len({e[4] for e in g}), len(ops),
                        len({e[2] for e in g} & victims),
                        "; ".join("%s=%d" % kv for kv in collections.Counter(e[9] for e in g).items()),
                        int(g[0][1] < KNOWN_INFECTION),
                        " || ".join("%s [%d]" % (k[:80], v) for k, v in ops.most_common()),
                        "; ".join("%s=%d" % kv for kv in ases.most_common())])
            for e in g:
                w2.writerow([i, e[1], e[2], e[3], e[4], ("AS" + ipas[e[4]][0]) if e[4] in ipas else "?",
                             e[5][:120], e[9], int(e[2] in victims)])
    base = collections.defaultdict(collections.Counter)
    for g in groups:
        m = g[0][1][:7]
        base[m]["all"] += 1
        if g[0][8] != "non-exit":
            base[m]["exit_policy"] += 1
        if g[0][8] in ("near-open", "OUR_POLICY"):
            base[m]["attacker_class"] += 1
        if {e[2] for e in g} & victims:
            base[m]["involving_victims"] += 1
    with open(os.path.join(args.out, "policy_change_groups_baseline.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "groups_all", "groups_to_exit_policy", "groups_to_attacker_class",
                    "groups_involving_victims"])
        for m in sorted(base):
            c = base[m]
            w.writerow([m, c["all"], c["exit_policy"], c["attacker_class"], c["involving_victims"]])
    print("qualifying groups:", len(groups))
    for m in sorted(base):
        print("  ", m, dict(base[m]))
    for i, g in enumerate(groups, 1):
        if g[0][8] != "non-exit" or ({e[2] for e in g} & victims):
            print("  group %d %s..%s relays=%d ops=%d class=%s victims=%d kinds=%s" % (
                i, g[0][1], g[-1][1], len({e[2] for e in g}), len({e[5] for e in g}), g[0][8],
                len({e[2] for e in g} & victims), dict(collections.Counter(e[9] for e in g))))


if __name__ == "__main__":
    main()
