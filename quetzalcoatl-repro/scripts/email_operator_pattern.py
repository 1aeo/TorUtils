#!/usr/bin/env python3
"""email_operator_pattern.py - operator-level pattern of the 377 victim relays, for the tor-relays email.

Tests, with net/netdb.sqlite (CollecTor 2026-05-01 00:00 .. 2026-10-07 02:18:04 UTC), the draft statements
  "X unique operators impacted", "all operators had relays on FranTech",
  "some operators had relays not on FranTech, not impacted", "FranTech relays are x % of the impact".

Definitions (same as NETWORK_FINDINGS.md):
  victim    relay that published >= 1 descriptor whose IPv4 policy summarizes (scripts/common.py
            summarize_policy, stored in policy.summary) to near-open or OUR_POLICY. The set is recomputed
            from the descriptor/policy tables and checked against net/victims.csv and the victim table.
  family    the 362 seeds (family_seed_fingerprints.txt) plus every fingerprint that published a
            descriptor whose contact starts with "email:Quetzalcoatl_relays[]proton.me".
  operator  exact contact string. The contact is taken from the victim's FIRST attacker-class descriptor
            (the script checks that all attacker descriptors of a relay carry one contact, and reports
            relays whose contact changed at any time in the window). Relays without a contact line are
            separate unknown operators; the count with all of them pooled as one is also printed.
  FranTech  AS53667 by CAIDA pfx2as 2026-10-01 (table ip_as, column asn).
  AS of a victim  AS of the IPv4 address of its first attacker-class descriptor (the last-descriptor IP
            and every attacker-descriptor IP are compared and differences reported).
  host      distinct IPv4 address.
  reference consensus  2026-10-01 14:00:00, the last consensus before the first attacker descriptor
            (2026-10-01 14:49:51). Contact / family of a relay in it come from the descriptor the
            consensus references (cons_entry.digest); if that digest is not in the DB, the relay's latest
            descriptor published at or before the valid-after time. "hit" = later a victim.

Per operator: victim relays, hosts, ASes; whether the operator (same exact contact; for a no-contact
operator: that relay) had ANY relay on FranTech at any time 2026-05-01 .. 2026-10-07 (any descriptor whose
address maps to AS53667), and in the reference consensus; its relays on other ASes (reference consensus
and any time) and how many were hit. For operators without FranTech relays, two extra checks: contact
variants (case/punctuation-insensitive, or one containing the other) on FranTech, and fingerprints the
victim relays declared in MyFamily that were on FranTech.

Outputs
  stdout                          the report (neutral labels only, no contact strings)
  net/email_operator_pattern.csv  one row per impacted operator (raw contact strings appear only here)

Usage: python3 -I scripts/email_operator_pattern.py > net/email_operator_pattern.log
"""
import argparse
import collections
import csv
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY, ts_epoch  # noqa: E402

FRANTECH = "53667"
REF_VA = "2026-10-01 14:00:00"
WIN_START = "2026-05-01 00:00:00"
FAMILY_CONTACT_PREFIX = "email:Quetzalcoatl_relays[]proton.me"
ATT_SUMMARIES = {NEAR_OPEN: "near-open", OUR_POLICY: "OUR_POLICY"}
NOCONTACT = "-"


def pct(a, b):
    return "%d/%d = %.1f %%" % (a, b, 100.0 * a / b) if b else "%d/0" % a


def norm_contact(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--victims", default="net/victims.csv")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    ap.add_argument("--out", default="net/email_operator_pattern.csv")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)

    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    ipas = {r[0]: (r[1] or "", r[2] or "", r[3] or "") for r in
            db.execute("SELECT ip, asn, as_name, org_name FROM ip_as")}
    asname = {}
    for ip, (a, n, o) in ipas.items():
        if a and a not in asname:
            asname[a] = o or n
    fran_ips = {ip for ip, v in ipas.items() if v[0] == FRANTECH}

    def asn(ip):
        v = ipas.get(ip)
        return v[0] if v and v[0] else "unmapped"

    def asl(a):
        return "AS%s %s" % (a, asname.get(a, "")) if a != "unmapped" else "unmapped"

    seeds = {l.split("#")[0].strip().upper() for l in open(args.seed) if len(l.split("#")[0].strip()) == 40}
    fam_ch = {h for h, t in contact.items() if (t or "").startswith(FAMILY_CONTACT_PREFIX)}
    fam_contact_fps = set()
    for h in fam_ch:
        fam_contact_fps |= {r[0] for r in db.execute("SELECT DISTINCT fp FROM descriptor WHERE contact_h=?", (h,))}
    family = seeds | fam_contact_fps
    print("== Inputs")
    print("descriptors:", db.execute("SELECT min(published), max(published), count(*) FROM descriptor").fetchone())
    print("consensuses:", db.execute("SELECT min(va), max(va), count(*) FROM consensus").fetchone())
    print("family fingerprints (seeds %d + family-contact %d, union) = %d; family contact strings: %d"
          % (len(seeds), len(fam_contact_fps), len(family), len(fam_ch)))
    print("FranTech AS53667 IPv4 addresses in ip_as:", len(fran_ips))

    # ------------------------------------------------------------------ victim set check
    att_h = {h for h, s in db.execute("SELECT policy_h, summary FROM policy") if s in ATT_SUMMARIES}
    v_db = {r[0] for r in db.execute(
        "SELECT DISTINCT fp FROM descriptor WHERE policy_h IN (%s)" % ",".join("?" * len(att_h)), sorted(att_h))}
    v_tab = {r[0] for r in db.execute("SELECT fp FROM victim")}
    vrows = list(csv.DictReader(open(args.victims)))
    v_csv = {r["fp"] for r in vrows}
    print("victims: recomputed from policy.summary %d, victim table %d, victims.csv %d, all equal: %s"
          % (len(v_db), len(v_tab), len(v_csv), v_db == v_tab == v_csv))
    fam_csv = {r["fp"] for r in vrows if r["family"] == "1"}
    print("family victims: victims.csv column %d, task definition %d, equal: %s"
          % (len(fam_csv), len(v_csv & family), fam_csv == (v_csv & family)))
    victims = sorted(v_db)

    # ------------------------------------------------------------------ per-victim facts
    V = {}
    contact_changed = []
    ip_note = []
    for fp in victims:
        ds = db.execute("""SELECT published, pub_epoch, nickname, address, contact_h, policy_h, family_h
                           FROM descriptor WHERE fp=? ORDER BY pub_epoch""", (fp,)).fetchall()
        att = [d for d in ds if d[5] in att_h]
        first, last = att[0], ds[-1]
        att_contacts = {d[4] for d in att}
        all_contacts = list(dict.fromkeys(d[4] for d in ds))
        if len(att_contacts) != 1:
            print("WARNING: attacker descriptors with several contacts:", fp)
        if len(all_contacts) > 1:
            contact_changed.append((fp, first[2], len(all_contacts),
                                    [d[0] for i, d in enumerate(ds) if i and d[4] != ds[i - 1][4]]))
        att_ips = list(dict.fromkeys(d[3] for d in att))
        a_first, a_last = asn(first[3]), asn(last[3])
        if a_first != a_last or len({asn(i) for i in att_ips}) > 1 or first[3] != last[3]:
            ip_note.append((fp, first[3], a_first, last[3], a_last, att_ips))
        fams = set()
        for d in ds:
            if d[6]:
                r = db.execute("SELECT fps FROM family WHERE family_h=?", (d[6],)).fetchone()
                if r and r[0]:
                    fams |= set(r[0].split())
        ch = first[4] or NOCONTACT
        V[fp] = {"fp": fp, "nick": first[2], "ip": first[3], "asn": a_first, "last_ip": last[3], "last_asn": a_last,
                 "att_asns": {asn(i) for i in att_ips}, "first_att": first[0], "contact_h": ch,
                 "family": fp in family, "declared_family": fams - {fp}}
    print("\n== Contacts and IPs of victims")
    print("victims whose contact string changed during the window: %d (all attacker descriptors of every victim"
          " carry one contact)" % len(contact_changed))
    for fp, nick, n, when in contact_changed:
        print("   %s %s: %d contact strings, changes at %s" % (fp, nick, n, ", ".join(when)))
    print("victims whose first-attacker-descriptor IP differs from the last-descriptor IP, or whose attacker"
          " descriptors span several IPs/ASes: %d" % len(ip_note))
    for x in ip_note:
        print("   %s first-attacker %s AS%s / last %s AS%s / attacker IPs %s" % x)
    unm = [v["fp"] for v in V.values() if v["asn"] == "unmapped"]
    print("victims with an unmapped IP:", len(unm))

    # ------------------------------------------------------------------ operators
    def opkey(v):
        return v["contact_h"] if v["contact_h"] != NOCONTACT else NOCONTACT + ":" + v["fp"]

    ops = collections.OrderedDict()
    for fp in victims:
        ops.setdefault(opkey(V[fp]), []).append(V[fp])
    pooled = {V[fp]["contact_h"] for fp in victims}

    def label(k, vs):
        if any(v["family"] for v in vs) and k in fam_ch:
            return "Quetzalcoatl family"
        nn = collections.Counter(v["nick"] for v in vs).most_common()
        nick = sorted(n for n, c in nn if c == nn[0][1])[0]
        return ("%s (no contact, %s)" % (vs[0]["nick"], vs[0]["fp"][:8])) if k.startswith(NOCONTACT + ":") else nick

    labels = {}
    for k, vs in ops.items():
        lab = label(k, vs)
        if lab in labels.values():
            lab += " (%s)" % sorted(v["fp"] for v in vs)[0][:8]
        labels[k] = lab

    # reference consensus
    ref = {}
    ref_va_e = ts_epoch(REF_VA)
    n_fallback = 0
    for fp, ip, dig in db.execute("SELECT fp, ip, digest FROM cons_entry WHERE va=?", (REF_VA,)).fetchall():
        d = db.execute("SELECT contact_h FROM descriptor WHERE digest=?", (dig,)).fetchone()
        if d is None:
            n_fallback += 1
            d = db.execute("SELECT contact_h FROM descriptor WHERE fp=? AND pub_epoch<=? ORDER BY pub_epoch DESC"
                           " LIMIT 1", (fp, ref_va_e)).fetchone()
        ch = (d[0] if d else None) or NOCONTACT
        ref[fp] = {"fp": fp, "ip": ip, "asn": asn(ip), "contact_h": ch, "family": fp in family,
                   "hit": fp in v_db, "key": ch if ch != NOCONTACT else NOCONTACT + ":" + fp}
    print("\n== Reference consensus %s: %d relays (%d without the referenced descriptor in the DB -> latest"
          " descriptor <= valid-after)" % (REF_VA, len(ref), n_fallback))
    ref_by_key = collections.defaultdict(list)
    for r in ref.values():
        ref_by_key[r["key"]].append(r)

    O = {}
    for k, vs in ops.items():
        is_nc = k.startswith(NOCONTACT + ":")
        if is_nc:
            q = db.execute("SELECT fp, address, contact_h, published FROM descriptor WHERE fp=?", (vs[0]["fp"],)).fetchall()
        else:
            q = db.execute("SELECT fp, address, contact_h, published FROM descriptor WHERE contact_h=?", (k,)).fetchall()
        win = [x for x in q if x[3] >= WIN_START]
        pre = [x for x in q if x[3] < WIN_START]
        fr_fps = {x[0] for x in win if x[1] in fran_ips}
        fr_fps_pre = {x[0] for x in pre if x[1] in fran_ips}
        fr_hosts = {x[1] for x in win if x[1] in fran_ips}
        non_fps = {x[0] for x in win if x[1] not in fran_ips}
        only_non = {fp for fp in non_fps if fp not in fr_fps}
        all_fps = {x[0] for x in win}
        rr = ref_by_key.get(k, [])
        rf = [r for r in rr if r["asn"] == FRANTECH]
        ro = [r for r in rr if r["asn"] != FRANTECH]
        ro_by = collections.defaultdict(lambda: [0, 0])
        for r in ro:
            ro_by[r["asn"]][0] += 1
            ro_by[r["asn"]][1] += r["hit"]
        vas = collections.Counter(v["asn"] for v in vs)
        vas_last = collections.Counter(v["last_asn"] for v in vs)
        o = {"key": k, "label": labels[k], "family": any(v["family"] for v in vs), "no_contact": is_nc,
             "vs": vs, "victim_fps": sorted(v["fp"] for v in vs), "hosts": {v["ip"] for v in vs},
             "hosts_last": {v["last_ip"] for v in vs}, "vas": vas, "vas_last": vas_last,
             "v_fr": sum(v["asn"] == FRANTECH for v in vs), "v_fr_last": sum(v["last_asn"] == FRANTECH for v in vs),
             "fr_any": bool(fr_fps), "fr_fps": fr_fps, "fr_fps_pre": fr_fps_pre, "fr_hosts": fr_hosts,
             "all_fps": all_fps, "non_fps": non_fps, "only_non": only_non,
             "only_non_hit": {fp for fp in only_non if fp in v_db}, "non_hit": {fp for fp in non_fps if fp in v_db},
             "ref": rr, "ref_fr": rf, "ref_other": ro, "ref_other_by": ro_by,
             "victims_not_in_ref": [v["fp"] for v in vs if v["fp"] not in ref]}
        O[k] = o
    fam_ops = [o for o in O.values() if o["family"]]
    nf_ops = [o for o in O.values() if not o["family"]]

    print("\n== (1) Unique operators impacted")
    print("total %d = family %d + non-family %d  (no-contact victims: %d relays, each a separate operator)"
          % (len(O), len(fam_ops), len(nf_ops), sum(o["no_contact"] for o in O.values())))
    print("with all no-contact relays pooled as one operator: %d (distinct contact strings incl. 'none')" % len(pooled))
    print("victim relays: %d = family %d + non-family %d" % (
        len(victims), sum(V[f]["family"] for f in victims), sum(not V[f]["family"] for f in victims)))
    size = collections.Counter(len(o["vs"]) for o in nf_ops)
    print("non-family operators by number of victim relays:", dict(sorted(size.items())))

    print("\n== (2) Impacted operators with a FranTech relay (same exact contact, any descriptor 2026-05-01..)")
    w_fr = [o for o in O.values() if o["fr_any"]]
    w_fr_ref = [o for o in O.values() if o["ref_fr"]]
    w_fr_v = [o for o in O.values() if o["v_fr"]]
    print("any time in window: %d of %d (family %d, non-family %d)" % (
        len(w_fr), len(O), sum(o["family"] for o in w_fr), sum(not o["family"] for o in w_fr)))
    print("in the reference consensus: %d of %d" % (len(w_fr_ref), len(O)))
    print("with a VICTIM relay on FranTech: %d of %d" % (len(w_fr_v), len(O)))
    print("pre-window descriptors (published < 2026-05-01) add FranTech relays for: %d operators" % sum(
        1 for o in O.values() if not o["fr_any"] and o["fr_fps_pre"]))
    print("ALL impacted operators had a FranTech relay:", len(w_fr) == len(O))
    no_fr = [o for o in O.values() if not o["fr_any"]]
    print("impacted operators WITHOUT any FranTech relay: %d (victim relays %d, hosts %d)" % (
        len(no_fr), sum(len(o["vs"]) for o in no_fr), len(set().union(*[o["hosts"] for o in no_fr])) if no_fr else 0))
    norm_map = collections.defaultdict(set)
    for h, t in contact.items():
        norm_map[norm_contact(t)].add(h)
    for o in sorted(no_fr, key=lambda o: -len(o["vs"])):
        # extra checks: contact variants on FranTech, declared family members on FranTech
        var_fr = set()
        if not o["no_contact"]:
            n0 = norm_contact(contact.get(o["key"], ""))
            cand = {h for nn, hs in norm_map.items() if nn and len(n0) >= 8 and (nn == n0 or n0 in nn or nn in n0)
                    for h in hs} - {o["key"]}
            for h in cand:
                var_fr |= {r[0] for r in db.execute("SELECT DISTINCT fp FROM descriptor WHERE contact_h=? AND "
                                                    "published>=?", (h, WIN_START))}
            var_fr = {fp for fp in var_fr if db.execute(
                "SELECT 1 FROM descriptor WHERE fp=? AND published>=? AND address IN (SELECT ip FROM ip_as WHERE asn=?)"
                " LIMIT 1", (fp, WIN_START, FRANTECH)).fetchone()}
        decl = set().union(*[v["declared_family"] for v in o["vs"]])
        decl_fr = {fp for fp in decl if db.execute(
            "SELECT 1 FROM descriptor WHERE fp=? AND published>=? AND address IN (SELECT ip FROM ip_as WHERE asn=?)"
            " LIMIT 1", (fp, WIN_START, FRANTECH)).fetchone()}
        o["variant_fr"], o["declared_fr"] = var_fr, decl_fr
        print("   %-26s victims %d %s | ASes %s | relays with this contact in window %d | FranTech via contact"
              " variant: %d, via declared MyFamily: %d" % (
                  o["label"], len(o["vs"]), " ".join(o["victim_fps"]),
                  ", ".join("%s=%d" % (asl(a), n) for a, n in o["vas"].most_common()), len(o["all_fps"]),
                  len(var_fr), len(decl_fr)))

    print("\n== (3) Impacted operators with FranTech relays that also had relays outside FranTech")
    for scope, ops_ in (("non-family", [o for o in w_fr if not o["family"]]), ("family", [o for o in w_fr if o["family"]])):
        ref_out = [o for o in ops_ if o["ref_other"]]
        n_out = sum(len(o["ref_other"]) for o in ops_)
        n_out_hit = sum(sum(r["hit"] for r in o["ref_other"]) for o in ops_)
        any_out = [o for o in ops_ if o["only_non"]]
        n_any = sum(len(o["only_non"]) for o in ops_)
        n_any_hit = sum(len(o["only_non_hit"]) for o in ops_)
        v_out = [o for o in ops_ if o["v_fr"] < len(o["vs"])]
        print("%s: %d operators with FranTech relays;" % (scope, len(ops_)))
        print("   reference consensus: %d of them also had relays on other ASes: %d such relays, %d hit"
              % (len(ref_out), n_out, n_out_hit))
        print("   any time in window: %d had relays never seen on FranTech: %d such relays, %d hit"
              % (len(any_out), n_any, n_any_hit))
        print("   operators with a victim relay outside FranTech: %d" % len(v_out))
        if scope == "non-family":
            for o in sorted(ref_out, key=lambda o: -len(o["ref_other"])):
                print("      %-26s FranTech ref %d/%d hit | other ASes ref %s" % (
                    o["label"], sum(r["hit"] for r in o["ref_fr"]), len(o["ref_fr"]),
                    "; ".join("%s %d/%d" % (asl(a), h, n) for a, (n, h) in sorted(o["ref_other_by"].items(),
                                                                               key=lambda kv: -kv[1][0]))))
            extra = [o for o in any_out if not o["ref_other"]]
            for o in extra:
                print("      (any time only) %-26s relays never on FranTech: %d, hit %d" % (
                    o["label"], len(o["only_non"]), len(o["only_non_hit"])))
    hit_out_ops = [o for o in O.values() if o["v_fr"] < len(o["vs"])]
    print("all impacted operators with >= 1 victim relay outside FranTech: %d (family %d, non-family %d: %s)" % (
        len(hit_out_ops), sum(o["family"] for o in hit_out_ops), sum(not o["family"] for o in hit_out_ops),
        ", ".join(o["label"] for o in hit_out_ops if not o["family"])))
    mixed = [o for o in nf_ops if 0 < o["v_fr"] < len(o["vs"])]
    print("non-family operators with victims both on and off FranTech:", len(mixed), [o["label"] for o in mixed])

    print("\n== (4) FranTech share of the impact (AS at first attacker descriptor; last-IP variant in brackets)")
    vf = [V[f] for f in victims]
    nf = [v for v in vf if not v["family"]]
    fam_v = [v for v in vf if v["family"]]

    def share(vs, key_ip, key_as):
        hosts = {v[key_ip] for v in vs}
        fr_hosts = {v[key_ip] for v in vs if v[key_as] == FRANTECH}
        return sum(v[key_as] == FRANTECH for v in vs), len(vs), len(fr_hosts), len(hosts)
    for name, vs in (("all", vf), ("non-family", nf), ("family", fam_v)):
        a, b, c, d = share(vs, "ip", "asn")
        a2, b2, c2, d2 = share(vs, "last_ip", "last_asn")
        print("%-10s relays %s [%s] | hosts %s [%s]" % (name, pct(a, b), pct(a2, b2), pct(c, d), pct(c2, d2)))
    print("operators: with a victim on FranTech %s; non-family %s; family %s" % (
        pct(len(w_fr_v), len(O)), pct(sum(not o["family"] for o in w_fr_v), len(nf_ops)),
        pct(sum(o["family"] for o in w_fr_v), len(fam_ops))))
    print("operators: with any FranTech relay %s; non-family %s" % (
        pct(len(w_fr), len(O)), pct(sum(not o["family"] for o in w_fr), len(nf_ops))))
    print("operators (no-contact pooled): with a victim on FranTech %d of %d" % (
        len({V[f]["contact_h"] for f in victims if V[f]["asn"] == FRANTECH}), len(pooled)))
    hosts_all = {v["ip"] for v in vf}
    hosts_fam = {v["ip"] for v in fam_v}
    hosts_nf = {v["ip"] for v in nf}
    print("hosts shared by family and non-family victims:", len(hosts_fam & hosts_nf), "; total hosts", len(hosts_all))
    va = collections.Counter(v["asn"] for v in vf)
    print("victims by AS (all / non-family / family):")
    for a, n in va.most_common():
        print("   %-45s %3d / %3d / %3d   hosts %d" % (asl(a), n, sum(v["asn"] == a for v in nf),
                                                       sum(v["asn"] == a for v in fam_v),
                                                       len({v["ip"] for v in vf if v["asn"] == a})))

    print("\n== (5) Reference-consensus hit rates, non-family relays")
    rnf = [r for r in ref.values() if not r["family"]]
    ins = [r for r in rnf if r["asn"] == FRANTECH]
    out = [r for r in rnf if r["asn"] != FRANTECH]
    print("inside FranTech: %s ; outside: %s" % (pct(sum(r["hit"] for r in ins), len(ins)),
                                               "%d/%d = %.3f %%" % (sum(r["hit"] for r in out), len(out),
                                                                     100.0 * sum(r["hit"] for r in out) / len(out))))
    h_in = collections.defaultdict(bool)
    for r in ins:
        h_in[r["ip"]] |= r["hit"]
    print("inside FranTech hosts: %d/%d hit" % (sum(h_in.values()), len(h_in)))
    o_in = collections.defaultdict(bool)
    for r in ins:
        o_in[r["key"]] |= r["hit"]
    print("inside FranTech operators (exact contact; no-contact separate): %d/%d hit" % (sum(o_in.values()), len(o_in)))
    ofr = {r["key"] for r in rnf if r["asn"] == FRANTECH}
    opx = collections.defaultdict(bool)
    for r in rnf:
        opx[r["key"]] |= r["hit"]
    a_ = sum(1 for k, h in opx.items() if k in ofr and h)
    c_ = sum(1 for k, h in opx.items() if k not in ofr and h)
    print("operator level (non-family, reference consensus): operators with a FranTech relay %d/%d hit;"
          " operators without %d/%d hit" % (a_, len(ofr), c_, len(opx) - len(ofr)))
    rfam = [r for r in ref.values() if r["family"]]
    print("family in reference consensus: %s hit" % pct(sum(r["hit"] for r in rfam), len(rfam)))
    print("victims not in the reference consensus: %d (family %d, non-family %d)" % (
        len(set(victims) - set(ref)), sum(V[f]["family"] for f in set(victims) - set(ref)),
        sum(not V[f]["family"] for f in set(victims) - set(ref))))
    # out-of-FranTech non-family hits at reference by AS
    ob = collections.defaultdict(lambda: [0, 0])
    for r in out:
        ob[r["asn"]][0] += 1
        ob[r["asn"]][1] += r["hit"]
    print("non-family hits outside FranTech at reference, by AS:",
          "; ".join("%s %d/%d" % (asl(a), h, n) for a, (n, h) in sorted(ob.items(), key=lambda kv: -kv[1][1]) if h))

    print("\n== (6) The family by AS")
    fa = collections.defaultdict(lambda: [0, 0])
    for r in rfam:
        fa[r["asn"]][0] += 1
        fa[r["asn"]][1] += r["hit"]
    fv = collections.Counter(v["asn"] for v in fam_v)
    fv_hosts = collections.defaultdict(set)
    for v in fam_v:
        fv_hosts[v["asn"]].add(v["ip"])
    orgs = collections.defaultdict(list)
    for a in set(fa) | set(fv):
        org = asname.get(a, a)
        orgs[org.split()[0] if org.lower().startswith("contabo") else org].append(a)
    print("ASes with family relays at reference: %d; ASes with family victims: %d; providers (Contabo's 3 ASes"
          " as one): %d" % (len(fa), len(fv), len(orgs)))
    for a in sorted(set(fa) | set(fv), key=lambda a: -fv.get(a, 0)):
        n, h = fa.get(a, (0, 0))
        print("   %-45s reference %d/%d hit | victims %d (hosts %d)" % (asl(a), h, n, fv.get(a, 0), len(fv_hosts[a])))

    fam_any = collections.defaultdict(set)
    for fp, addr in db.execute("SELECT DISTINCT fp, address FROM descriptor WHERE published>=? AND fp IN (%s)" % (
            ",".join("?" * len(family))), [WIN_START] + sorted(family)):
        fam_any[asn(addr)].add(fp)
    print("family fingerprints by AS of any descriptor address in the window (a relay can count on several ASes):",
          "; ".join("%s %d" % (asl(a), len(s)) for a, s in sorted(fam_any.items(), key=lambda kv: -len(kv[1]))))

    print("\n== Extra context")
    nf_fr_noref = [o for o in nf_ops if o["fr_any"] and not o["ref_fr"]]
    print("non-family impacted operators with FranTech relays but none in the reference consensus: %d %s" % (
        len(nf_fr_noref), [(o["label"], o["victims_not_in_ref"]) for o in nf_fr_noref]))
    nref = sorted(set(victims) - set(ref))
    print("victims not in the reference consensus:")
    for fp in nref:
        v = V[fp]
        print("   %s %-18s %s family=%d first attacker descriptor %s" % (fp, v["nick"], asl(v["asn"]), v["family"],
                                                                         v["first_att"]))
    # every operator (non-family) that had a FranTech relay at any time in the window: how many impacted
    fr_ops = set()
    for fp, ch in db.execute("SELECT DISTINCT fp, contact_h FROM descriptor WHERE published>=? AND address IN "
                             "(SELECT ip FROM ip_as WHERE asn=?)", (WIN_START, FRANTECH)):
        if fp in family:
            continue
        fr_ops.add(ch if ch and ch != NOCONTACT else NOCONTACT + ":" + fp)
    imp = {o["key"] for o in nf_ops}
    print("non-family operators with >= 1 FranTech relay at any time in the window: %d; impacted: %d; not impacted: %d"
          % (len(fr_ops), len(fr_ops & imp), len(fr_ops - imp)))
    fr_relays = {r[0] for r in db.execute("SELECT DISTINCT fp FROM descriptor WHERE published>=? AND address IN "
                                          "(SELECT ip FROM ip_as WHERE asn=?)", (WIN_START, FRANTECH))}
    print("FranTech relays (fingerprints) at any time in the window: %d (non-family %d), victims among them %d"
          " (non-family %d)" % (len(fr_relays), len(fr_relays - family), len(fr_relays & v_db),
                                len((fr_relays - family) & v_db)))

    # ------------------------------------------------------------------ CSV
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "family", "no_contact", "contact", "victim_relays", "victim_fps", "victim_nicknames",
                    "victim_hosts", "victim_ips", "victim_ases_first_attacker_ip", "victim_ases_last_ip",
                    "victims_on_frantech", "frantech_relay_any_time", "frantech_fps_any_time",
                    "frantech_hosts_any_time", "relays_with_contact_any_time", "relays_never_on_frantech_any_time",
                    "relays_never_on_frantech_hit", "ref_relays", "ref_frantech_relays", "ref_frantech_hit",
                    "ref_other_relays", "ref_other_hit", "ref_other_ases", "victims_not_in_ref",
                    "no_frantech_variant_contact_fps_on_frantech", "no_frantech_declared_family_fps_on_frantech"])
        for o in sorted(O.values(), key=lambda o: (-len(o["vs"]), o["label"])):
            w.writerow([o["label"], int(o["family"]), int(o["no_contact"]),
                        "" if o["no_contact"] else contact.get(o["key"], ""), len(o["vs"]), " ".join(o["victim_fps"]),
                        " ".join(sorted({v["nick"] for v in o["vs"]})), len(o["hosts"]),
                        " ".join(sorted(o["hosts"])),
                        "; ".join("AS%s=%d" % kv for kv in o["vas"].most_common()),
                        "; ".join("AS%s=%d" % kv for kv in o["vas_last"].most_common()),
                        o["v_fr"], int(o["fr_any"]), len(o["fr_fps"]), len(o["fr_hosts"]), len(o["all_fps"]),
                        len(o["only_non"]), len(o["only_non_hit"]), len(o["ref"]), len(o["ref_fr"]),
                        sum(r["hit"] for r in o["ref_fr"]), len(o["ref_other"]),
                        sum(r["hit"] for r in o["ref_other"]),
                        "; ".join("AS%s %d/%d hit" % (a, h, n) for a, (n, h) in sorted(o["ref_other_by"].items(),
                                                                                    key=lambda kv: -kv[1][0])),
                        " ".join(o["victims_not_in_ref"]),
                        " ".join(sorted(o.get("variant_fr", ()))), " ".join(sorted(o.get("declared_fr", ())))])
    print("\nwrote", args.out, "(%d operators)" % len(O))


if __name__ == "__main__":
    main()
