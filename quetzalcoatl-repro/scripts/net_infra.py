#!/usr/bin/env python3
"""net_infra.py - infrastructure / provider analysis of the victims (network-wide).

Reference population: every relay in the consensus valid just before the first attacker-class descriptor
(first descriptor anywhere whose policy summarizes to near-open or OUR_POLICY; the consensus with the
latest valid-after <= that publication time). Hit = the relay later became a victim (victim table).
The Quetzalcoatl family (seeds + exact family contact) is reported separately because its relays were
reached through the family's own compromised management infrastructure.

Outputs (net/):
  as_hit_rates.csv             per AS: relays present, exits, victims, hit rates (all / non-family)
  provider_profile_relays.csv  every relay of the most affected provider (non-family) with profile and hit
  provider_profile_tests.csv   hit vs not-hit comparisons inside the provider at relay, host and operator
                               level (version, OS, family-cert, IPv6, age, /16 block, country, exit status)
  provider_stratified.csv      inside vs outside the provider, stratified by profile (Mantel-Haenszel)
  multi_provider_operators.csv operators with relays on several ASes: which providers were hit
  newcomers.csv                victims (and provider relays) first seen shortly before the waves; contacts
                               with placeholder / random-looking patterns
"""
import argparse
import collections
import csv
import math
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ts_epoch  # noqa: E402

FAMILY_CONTACT_PREFIX = "email:Quetzalcoatl_relays[]proton.me"


def fisher_two_sided(a, b, c, d):
    """2x2 table [[a,b],[c,d]]; two-sided Fisher exact p-value."""
    n = a + b + c + d
    r1, c1 = a + b, a + c

    def p(x):
        return math.comb(r1, x) * math.comb(n - r1, c1 - x) / math.comb(n, c1)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    p0 = p(a)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 * (1 + 1e-9)))


def mantel_haenszel(strata):
    """strata: list of (a,b,c,d) with a=exposed&hit, b=exposed&not, c=unexposed&hit, d=unexposed&not."""
    num = den = 0.0
    sa = se = sv = 0.0
    for a, b, c, d in strata:
        n = a + b + c + d
        if n < 2:
            continue
        num += a * d / n
        den += b * c / n
        r1, r0, m1, m0 = a + b, c + d, a + c, b + d
        sa += a
        se += r1 * m1 / n
        sv += r1 * r0 * m1 * m0 / (n * n * (n - 1)) if n > 1 else 0
    or_ = num / den if den else float("inf")
    chi = (abs(sa - se) - 0.5) ** 2 / sv if sv else 0.0
    p = math.erfc(math.sqrt(chi / 2)) if chi > 0 else 1.0
    return or_, chi, p


def os_of(platform):
    m = re.search(r" on (\S+)", platform or "")
    return m.group(1) if m else "?"


def ver_of(platform):
    m = re.search(r"Tor (\d+\.\d+\.\d+)\.(\d+)", platform or "")
    return (m.group(1) + "." + m.group(2)) if m else "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    O = lambda n: os.path.join(args.out, n)  # noqa: E731
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    seeds = {l.split("#")[0].strip().upper() for l in open(args.seed) if len(l.split("#")[0].strip()) == 40}
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    ipas = {r[0]: r[1:] for r in db.execute("SELECT ip, asn, as_name, org_name, ipfire_cc FROM ip_as")}
    t0_pub, t0_fp = db.execute("""SELECT d.published, d.fp FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                                  WHERE p.class IN ('near-open','OUR_POLICY') ORDER BY d.pub_epoch LIMIT 1""").fetchone()
    va0 = db.execute("SELECT max(va) FROM consensus WHERE va <= ?", (t0_pub,)).fetchone()[0]
    print("first attacker descriptor:", t0_pub, t0_fp, "; reference consensus:", va0)
    pres = db.execute("SELECT fp, ip, flags, policy, version, bw, nickname FROM cons_entry WHERE va=?", (va0,)).fetchall()
    t0e = ts_epoch(t0_pub)
    rel = {}
    for fp, ip, flags, pol, ver, bw, nick in pres:
        d = db.execute("""SELECT platform, contact_h, family_cert, or_addresses, ipv6_policy, family_n FROM descriptor
                          WHERE fp=? AND pub_epoch<=? ORDER BY pub_epoch DESC LIMIT 1""", (fp, t0e)).fetchone()
        first = db.execute("SELECT min(start_va) FROM cons_interval WHERE fp=?", (fp,)).fetchone()[0]
        firstd = db.execute("SELECT min(published) FROM descriptor WHERE fp=?", (fp,)).fetchone()[0]
        ct = contact.get(d[1], "") if d else ""
        fam = fp in seeds or ct.startswith(FAMILY_CONTACT_PREFIX)
        a = ipas.get(ip, ("?", "?", "?", "?"))
        rel[fp] = {"fp": fp, "ip": ip, "nick": nick, "asn": a[0] or "?", "as_name": a[2] or a[1] or "?", "cc": a[3],
                   "exit_flag": "Exit" in flags.split(), "exit_policy": pol != "reject 1-65535",
                   "guard": "Guard" in flags.split(), "version": ver_of(d[0] if d else ver), "os": os_of(d[0] if d else ""),
                   "family_cert": bool(d and d[2]), "ipv6": bool(d and "[" in (d[3] or "")),
                   "declares_family": bool(d and d[5]), "contact": ct or "(none)", "family": fam,
                   "first_seen": first, "first_desc": firstd, "hit": fp in victims, "bw": bw,
                   "block16": ".".join(ip.split(".")[:2]), "block24": ".".join(ip.split(".")[:3])}
    allr = list(rel.values())
    print("relays in reference consensus:", len(allr), "; of which later victims:", sum(r["hit"] for r in allr),
          "; victims not present then:", len(victims - set(rel)))
    # ------------------------------------------------ per-AS hit rates
    per = collections.defaultdict(lambda: collections.Counter())
    for r in allr:
        k = (r["asn"], r["as_name"])
        c = per[k]
        c["relays"] += 1
        c["exit_policy"] += r["exit_policy"]
        c["hit"] += r["hit"]
        if not r["family"]:
            c["nf_relays"] += 1
            c["nf_hit"] += r["hit"]
            c["nf_exit_policy"] += r["exit_policy"]
            c["nf_exit_hit"] += r["hit"] and r["exit_policy"]
            c["nf_nonexit"] += not r["exit_policy"]
            c["nf_nonexit_hit"] += r["hit"] and not r["exit_policy"]
        else:
            c["fam_relays"] += 1
            c["fam_hit"] += r["hit"]
    rows = []
    for (asn, name), c in per.items():
        rows.append([asn, name, c["relays"], c["exit_policy"], c["hit"], round(c["hit"] / c["relays"], 4),
                     c["fam_relays"], c["fam_hit"], c["nf_relays"], c["nf_hit"],
                     round(c["nf_hit"] / c["nf_relays"], 4) if c["nf_relays"] else "",
                     c["nf_exit_policy"], c["nf_exit_hit"], c["nf_nonexit"], c["nf_nonexit_hit"]])
    rows.sort(key=lambda r: (-r[4], -r[2]))
    with open(O("as_hit_rates.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["asn", "as_name", "relays_present", "exit_policy_relays", "victims", "hit_rate", "family_relays",
                    "family_victims", "nonfamily_relays", "nonfamily_victims", "nonfamily_hit_rate",
                    "nonfamily_exit_policy_relays", "nonfamily_exit_victims", "nonfamily_nonexit_relays",
                    "nonfamily_nonexit_victims"])
        w.writerows(rows)
    print("per-AS hit rates (ASes with victims):")
    for r in rows:
        if r[4]:
            print("   AS%s %-28s present=%d victims=%d (%.1f%%) | family %d/%d | non-family %d/%d (%s) exits %d/%d nonexits %d/%d" % (
                r[0], r[1][:28], r[2], r[4], 100 * r[5], r[7], r[6], r[9], r[8], r[10], r[12], r[11], r[14], r[13]))
    top = max(rows, key=lambda r: r[9])
    PASN = top[0]
    print("most affected provider (non-family victims):", PASN, top[1])
    inside = [r for r in allr if r["asn"] == PASN and not r["family"]]
    outside = [r for r in allr if r["asn"] != PASN and not r["family"]]
    hi = sum(r["hit"] for r in inside)
    ho = sum(r["hit"] for r in outside)
    print("non-family relays: inside %d hit %d (%.2f%%); outside %d hit %d (%.3f%%); Fisher p=%.3g" % (
        len(inside), hi, 100 * hi / len(inside), len(outside), ho, 100 * ho / len(outside),
        fisher_two_sided(hi, len(inside) - hi, ho, len(outside) - ho)))
    with open(O("provider_profile_relays.csv"), "w", newline="") as f:
        w = csv.writer(f)
        keys = ["fp", "nick", "ip", "block16", "cc", "hit", "exit_flag", "exit_policy", "guard", "version", "os",
                "family_cert", "declares_family", "ipv6", "first_seen", "first_desc", "bw", "contact"]
        w.writerow(keys)
        for r in sorted(inside, key=lambda r: r["ip"]):
            w.writerow([r[k] for k in keys])
    # ------------------------------------------------ hit vs not-hit inside the provider
    tests = []

    def compare(level, units, attr, fn):
        vals = collections.defaultdict(lambda: [0, 0])
        for u in units:
            vals[fn(u)][0 if u["hit"] else 1] += 1
        for v, (h, n) in sorted(vals.items(), key=lambda kv: -sum(kv[1])):
            oh = sum(x[0] for k, x in vals.items() if k != v)
            on = sum(x[1] for k, x in vals.items() if k != v)
            p = fisher_two_sided(h, n, oh, on)
            tests.append([level, attr, v, h, n, round(h / (h + n), 3) if h + n else "", oh, on, "%.3g" % p])

    # relay level
    rel_units = inside
    for attr, fn in [("version", lambda u: u["version"]), ("os", lambda u: u["os"]),
                     ("family_cert", lambda u: u["family_cert"]), ("declares_family", lambda u: u["declares_family"]),
                     ("ipv6", lambda u: u["ipv6"]), ("exit_policy_at_t0", lambda u: u["exit_policy"]),
                     ("exit_flag_at_t0", lambda u: u["exit_flag"]), ("guard", lambda u: u["guard"]),
                     ("block16", lambda u: u["block16"]), ("country", lambda u: u["cc"]),
                     ("age_first_seen_before_2026-05-02", lambda u: (u["first_seen"] or "9") < "2026-05-02"),
                     ("has_contact", lambda u: u["contact"] != "(none)")]:
        compare("relay", rel_units, attr, fn)
    # host level: a host is hit if any relay on it is hit
    hosts = collections.defaultdict(list)
    for r in inside:
        hosts[r["ip"]].append(r)
    host_units = []
    for ip, rs in hosts.items():
        host_units.append({"hit": any(r["hit"] for r in rs), "block16": rs[0]["block16"], "cc": rs[0]["cc"],
                           "os": rs[0]["os"], "multi_relay": len(rs) > 1, "exit_policy": any(r["exit_policy"] for r in rs),
                           "ipv6": any(r["ipv6"] for r in rs), "version": rs[0]["version"],
                           "family_cert": any(r["family_cert"] for r in rs)})
    for attr in ["block16", "cc", "os", "multi_relay", "exit_policy", "ipv6", "version", "family_cert"]:
        compare("host", host_units, attr, lambda u, a=attr: u[a])
    # operator level (operators = exact contact; no-contact relays each separate)
    ops = collections.defaultdict(list)
    for r in inside:
        ops[r["contact"] if r["contact"] != "(none)" else "(none)" + r["fp"]].append(r)
    op_units = []
    for op, rs in ops.items():
        op_units.append({"hit": any(r["hit"] for r in rs), "size": "1" if len(rs) == 1 else ("2-4" if len(rs) < 5 else "5+"),
                         "has_contact": not op.startswith("(none)"), "exit_policy": any(r["exit_policy"] for r in rs),
                         "family_cert": any(r["family_cert"] for r in rs), "ipv6": any(r["ipv6"] for r in rs)})
    for attr in ["size", "has_contact", "exit_policy", "family_cert", "ipv6"]:
        compare("operator", op_units, attr, lambda u, a=attr: u[a])
    with open(O("provider_profile_tests.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["level", "attribute", "value", "hit", "not_hit", "hit_rate", "other_values_hit",
                    "other_values_not_hit", "fisher_p_value_vs_other_values"])
        w.writerows(tests)
    print("inside provider: relays %d (hit %d), hosts %d (hit %d), operators %d (hit %d)" % (
        len(inside), hi, len(host_units), sum(u["hit"] for u in host_units), len(op_units), sum(u["hit"] for u in op_units)))
    for t in tests:
        if float(t[8]) < 0.05 or t[1] in ("exit_policy_at_t0", "block16", "country", "multi_relay", "size"):
            print("   ", t)
    # ------------------------------------------------ stratified inside vs outside (non-family)
    def stratum(r):
        return (("exit" if r["exit_policy"] else "nonexit"), r["version"][:7], r["os"], r["family_cert"], r["ipv6"])
    st = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in inside:
        st[stratum(r)][0 if r["hit"] else 1] += 1
    for r in outside:
        st[stratum(r)][2 if r["hit"] else 3] += 1
    srows = []
    for k, v in sorted(st.items(), key=lambda kv: -sum(kv[1])):
        if v[0] + v[1] == 0:
            continue
        srows.append(list(k) + v + [round(v[0] / (v[0] + v[1]), 3), round(v[2] / (v[2] + v[3]), 4) if v[2] + v[3] else ""])
    or_, chi, p = mantel_haenszel([tuple(v) for v in st.values()])
    st2 = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in inside:
        st2[("exit" if r["exit_policy"] else "nonexit")][0 if r["hit"] else 1] += 1
    for r in outside:
        st2[("exit" if r["exit_policy"] else "nonexit")][2 if r["hit"] else 3] += 1
    or2, chi2, p2 = mantel_haenszel([tuple(v) for v in st2.values()])
    # operator level: operators with any relay inside vs operators only outside
    opx = collections.defaultdict(lambda: {"in": False, "hit": False, "hit_in": False, "hit_out": False, "ases": set()})
    for r in allr:
        if r["family"]:
            continue
        k = r["contact"] if r["contact"] != "(none)" else "(none)" + r["fp"]
        o = opx[k]
        o["ases"].add(r["asn"])
        if r["asn"] == PASN:
            o["in"] = True
        if r["hit"]:
            o["hit"] = True
            if r["asn"] == PASN:
                o["hit_in"] = True
            else:
                o["hit_out"] = True
    a = sum(1 for o in opx.values() if o["in"] and o["hit"])
    b = sum(1 for o in opx.values() if o["in"] and not o["hit"])
    c = sum(1 for o in opx.values() if not o["in"] and o["hit"])
    d = sum(1 for o in opx.values() if not o["in"] and not o["hit"])
    with open(O("provider_stratified.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["exit_status", "version", "os", "family_cert", "ipv6", "inside_hit", "inside_not", "outside_hit",
                    "outside_not", "inside_rate", "outside_rate"])
        w.writerows(srows)
        w.writerow([])
        w.writerow(["MH odds ratio (5-way strata)", or_, "CMH chi2", round(chi, 2), "p", "%.3g" % p])
        w.writerow(["MH odds ratio (exit status only)", or2, "CMH chi2", round(chi2, 2), "p", "%.3g" % p2])
        w.writerow(["operator level: inside hit/not", a, b, "outside-only hit/not", c, d, "Fisher p",
                    "%.3g" % fisher_two_sided(a, b, c, d)])
    print("stratified (exit,version,os,family-cert,ipv6): MH OR=%s chi2=%.1f p=%.3g; exit-only: OR=%s chi2=%.1f p=%.3g" % (
        or_, chi, p, or2, chi2, p2))
    print("operator level: inside hit %d / not %d ; outside-only hit %d / not %d ; Fisher p=%.3g" % (
        a, b, c, d, fisher_two_sided(a, b, c, d)))
    print("strata with inside relays (top 12):")
    for r in srows[:12]:
        print("   ", r)
    # ------------------------------------------------ multi-provider operators
    mrows = []
    for k, o in opx.items():
        if len(o["ases"]) > 1 and (o["hit"] or o["in"]):
            rs = [r for r in allr if not r["family"] and (r["contact"] if r["contact"] != "(none)" else "(none)" + r["fp"]) == k]
            by = collections.defaultdict(lambda: [0, 0])
            for r in rs:
                by[r["asn"] + " " + r["as_name"][:25]][0] += 1
                by[r["asn"] + " " + r["as_name"][:25]][1] += r["hit"]
            mrows.append([k[:120], len(rs), len(o["ases"]), int(o["in"]), int(o["hit_in"]), int(o["hit_out"]),
                          "; ".join("%s: %d relays, %d hit" % (a_, v[0], v[1]) for a_, v in sorted(by.items(), key=lambda kv: -kv[1][0]))])
    mrows.sort(key=lambda r: (-r[4] - r[5], -r[1]))
    with open(O("multi_provider_operators.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["operator", "relays", "ases", "on_provider", "hit_on_provider", "hit_elsewhere", "breakdown"])
        w.writerows(mrows)
    print("multi-provider operators touching the provider or hit: %d; hit on provider: %d; hit elsewhere: %d" % (
        len(mrows), sum(r[4] for r in mrows), sum(r[5] for r in mrows)))
    for r in mrows:
        if r[4] or r[5]:
            print("   ", r)
    # ------------------------------------------------ newcomers / odd contacts
    nrows = []
    for fp in sorted(victims):
        fd = db.execute("SELECT min(published) FROM descriptor WHERE fp=?", (fp,)).fetchone()[0]
        d = db.execute("SELECT nickname, address, contact_h, platform FROM descriptor WHERE fp=? ORDER BY pub_epoch DESC LIMIT 1", (fp,)).fetchone()
        ct = contact.get(d[2], "(none)")
        odd = bool(re.search(r"\.example\b|@example|nocontact|no.?warn|-{5,}|^[a-z0-9]{8,}@", ct, re.I)) or ct == "(none)"
        if fd >= "2026-08-01" or odd:
            if fp in seeds or ct.startswith(FAMILY_CONTACT_PREFIX):
                continue
            a = ipas.get(d[1], ("?", "?", "?", "?"))
            nrows.append([fp, d[0], d[1], "AS" + a[0], a[2] or a[1], fd, ct[:100], int(fd >= "2026-08-01"), int(odd), d[3]])
    with open(O("newcomers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "nickname", "ip", "asn", "as_name", "first_descriptor_in_window", "contact",
                    "first_seen_after_2026-08-01", "odd_contact", "platform"])
        w.writerows(nrows)
    print("victim newcomers / odd contacts (non-family):", len(nrows))
    for r in nrows:
        print("   ", r[:8])
    # provider newcomers in the 30 days before the waves (all relays, hit or not)
    newp = [r for r in inside if (r["first_desc"] or "") >= "2026-09-01"]
    print("non-family provider relays first published >= 2026-09-01 present at reference consensus:", len(newp),
          "hit:", sum(r["hit"] for r in newp))


if __name__ == "__main__":
    main()
