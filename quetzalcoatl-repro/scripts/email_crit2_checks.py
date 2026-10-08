"""email_crit2_checks.py - spot checks for critique round 2 of the tor-relays reply draft.

Read-only on net/netdb.sqlite and net/*.csv; standard library only; run as python3 -I.
Each check prints the numbers the draft cites, recomputed from the DB:
  C1  victims, hosts (IPv4 of first attacker descriptor), ASes, operators
  C2  first OUR_POLICY descriptors (TorDola), reload vs restart
  C3  10-01 15:33:55-15:39:19 OUR_POLICY wave
  C4  family near-open flip 10-02; family relays active in October
  C5  10-02 09:29:25-09:44:12 non-family changes; byte-exact reverts
  C6  10-05 11:00 / 12:00 attacker p lines and flags
  C7  first BadExit of 9CDB4020 in cons_interval
  C8  non-exit victims, family share, Exit flag gained
  C9  victims flagged in consensus / votes; split of never-flagged-in-vote
  C10 family restarts 10-01 15:36:30-15:47:53 (hosts)
  C11 no-contact victims, hosts
  C12 victims listed in consensuses 10-05 17:00 .. 10-07 02:00
  C13 non-family relays on family ASes at 10-01 14:00 (hit)
  C14 FranTech hit rates at 10-01 14:00 (non-family)

Usage: python3 -I scripts/email_crit2_checks.py
"""
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "net", "netdb.sqlite")
ATT = {common.NEAR_OPEN: "near-open", common.OUR_POLICY: "OUR_POLICY"}
FRANTECH = "53667"
REF_VA = "2026-10-01 14:00:00"


def main():
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    seeds = {l.strip().upper() for l in open(os.path.join(BASE, "family_seed_fingerprints.txt"))
             if l.strip() and not l.startswith("#")}
    fam_ch = {h for (h, t) in c.execute("select contact_h, text from contact")
              if t and t.startswith("email:Quetzalcoatl_relays[]proton.me")}
    fam = set(seeds)
    for (fp,) in c.execute("select distinct fp from descriptor where contact_h in (%s)"
                           % ",".join("?" * len(fam_ch)), list(fam_ch)):
        fam.add(fp)
    print("family fps", len(fam))
    asn = dict(c.execute("select ip, asn from ip_as"))
    contact = dict(c.execute("select contact_h, text from contact"))
    victims = [r[0] for r in c.execute("select fp from victim")]
    vset = set(victims)

    # descriptors of victims, ordered
    descs = collections.defaultdict(list)
    q = ("select d.fp, d.published, d.pub_epoch, d.address, d.boot_epoch, d.contact_h, d.policy_h,"
         " p.summary, p.class from descriptor d join policy p using(policy_h) where d.fp in (%s)"
         " order by d.fp, d.pub_epoch")
    for r in c.execute(q % ",".join("?" * len(victims)), victims):
        descs[r[0]].append(r[1:])
    first_att = {}
    for fp, ds in descs.items():
        for i, d in enumerate(ds):
            if d[6] in ATT:
                prev = ds[i - 1] if i else None
                kind = "first" if prev is None else (
                    "reload" if abs(d[3] - prev[3]) <= 2 else "restart")
                first_att[fp] = (d, prev, kind)
                break

    def op(fp):
        ch = first_att[fp][0][4]
        t = contact.get(ch) if ch else None
        return t if t else "nocontact:" + fp

    # C1
    hosts = {first_att[fp][0][2] for fp in victims}
    ases = {asn.get(first_att[fp][0][2]) for fp in victims}
    ops = {op(fp) for fp in victims}
    nf = [fp for fp in victims if fp not in fam]
    print("C1 victims", len(victims), "hosts", len(hosts), "ASes", len(ases), "operators", len(ops),
          "nonfam victims", len(nf), "nonfam ops", len({op(fp) for fp in nf}),
          "family victims", len(vset & fam))
    ft = [fp for fp in victims if asn.get(first_att[fp][0][2]) == FRANTECH]
    print("   FranTech victims", len(ft), "hosts", len({first_att[fp][0][2] for fp in ft}),
          "ops", len({op(fp) for fp in ft}), "nonfam", len([f for f in ft if f not in fam]),
          "nonfam hosts", len({first_att[f][0][2] for f in ft if f not in fam}),
          "nonfam all hosts", len({first_att[f][0][2] for f in nf}))

    # C2/C3/C4/C5 windows on first attacker descriptor
    def window(lo, hi, sel=lambda fp: True):
        out = [fp for fp in victims if lo <= first_att[fp][0][0] <= hi and sel(fp)]
        return out
    w = window("2026-10-01 14:49:00", "2026-10-01 14:51:00")
    print("C2", sorted((first_att[f][0][0], f, first_att[f][2], asn.get(first_att[f][0][2])) for f in w))
    w = window("2026-10-01 15:33:55", "2026-10-01 15:39:19")
    print("C3 relays", len(w), "hosts", len({first_att[f][0][2] for f in w}), "ops", len({op(f) for f in w}),
          "nocontact", sum(1 for f in w if op(f).startswith("nocontact")),
          "FranTech", sum(1 for f in w if asn.get(first_att[f][0][2]) == FRANTECH),
          "kinds", collections.Counter(first_att[f][2] for f in w), "family", len(set(w) & fam),
          "classes", collections.Counter(first_att[f][0][6] for f in w))
    fv = [f for f in victims if f in fam]
    t = sorted(first_att[f][0][0] for f in fv)
    print("C4 family victims", len(fv), "range", t[0], t[-1], "hosts", len({first_att[f][0][2] for f in fv}),
          "kinds", collections.Counter(first_att[f][2] for f in fv),
          "first", min(fv, key=lambda f: first_att[f][0][1]),
          "classes", collections.Counter(first_att[f][0][6] for f in fv))
    oct_fam = {r[0] for r in c.execute("select distinct fp from descriptor where published >= '2026-10-01'")} & fam
    print("   family fps with a descriptor published in Oct", len(oct_fam), "non-victims", len(oct_fam - vset))
    ref_fam = {r[0] for r in c.execute("select fp from cons_entry where va=?", (REF_VA,))} & fam
    print("   family fps in", REF_VA, len(ref_fam), "victims", len(ref_fam & vset))

    # C5: all policy changes of non-family relays 10-02 09:29:25-09:44:12
    ev = []
    for fp in nf:
        ds = descs[fp]
        for i in range(1, len(ds)):
            d, p = ds[i], ds[i - 1]
            if "2026-10-02 09:29:25" <= d[0] <= "2026-10-02 09:44:12" and d[5] != p[5]:
                ev.append((fp, p, d))
    cnt = collections.Counter()
    byte = 0
    for fp, p, d in ev:
        oc, nc = p[7], d[7]
        if nc == "near-open":
            cnt["to near-open from " + oc] += 1
        else:
            cnt["%s -> %s" % (oc, nc)] += 1
            if oc == "OUR_POLICY":
                # policy before the first attacker descriptor
                pre = first_att[fp][1]
                same = pre is not None and pre[5] == d[5]
                byte += same
                print("   revert", fp, d[0], nc, "byte-exact-to-pre-attack" if same else "DIFFERENT", pre and pre[7])
    print("C5 events", len(ev), "relays", len({e[0] for e in ev}), dict(cnt), "byte-exact reverts", byte,
          "FranTech", sum(1 for e in ev if asn.get(e[2][2]) == FRANTECH))

    # C6
    for va in ("2026-10-05 11:00:00", "2026-10-05 12:00:00"):
        rows = c.execute("select fp, flags, policy from cons_entry where va=?", (va,)).fetchall()
        a = [r for r in rows if (r[2] or "") in ATT]
        fl = [r for r in a if "BadExit" in r[1].split() or "MiddleOnly" in r[1].split()]
        print("C6", va, "attacker p", len(a), "flagged", len(fl))

    # C7
    rows = c.execute("select start_va, end_va, flags, policy from cons_interval where fp=? order by start_va",
                     ("9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76",)).fetchall()
    fb = [r for r in rows if "BadExit" in r[2].split()]
    print("C7 9CDB first interval", rows[0][:2], "first BadExit interval", fb[0][:3] if fb else None,
          "first MiddleOnly", next((r[:3] for r in rows if "MiddleOnly" in r[2].split()), None))

    # C8 non-exit victims
    vic = {r["fp"]: r for r in csv.DictReader(open(os.path.join(BASE, "net", "victims.csv")))}
    ne = [f for f in victims if vic[f]["class_before_first_attacker_desc"] == "non-exit"]
    got = 0
    for f in ne:
        fa = first_att[f][0][0]
        r = c.execute("select count(*) from cons_entry where fp=? and va>=? and (' '||flags||' ') like '% Exit %'",
                      (f, fa)).fetchone()[0]
        got += r > 0
    print("C8 non-exit victims", len(ne), "family", len(set(ne) & fam), "got Exit", got,
          "classes", collections.Counter(vic[f]["class_before_first_attacker_desc"] for f in victims))

    # C9 flags
    fc = fvote = 0
    novote = []
    for f in victims:
        fa = first_att[f][0][0]
        r = c.execute("select count(*) from cons_entry where fp=? and va>=? and "
                      "((' '||flags||' ') like '% BadExit %' or (' '||flags||' ') like '% MiddleOnly %')",
                      (f, fa)).fetchone()[0]
        fc += r > 0
        r = c.execute("select count(*) from vote_entry where fp=? and va>=? and "
                      "((' '||flags||' ') like '% BadExit %' or (' '||flags||' ') like '% MiddleOnly %')",
                      (f, fa)).fetchone()[0]
        if r:
            fvote += 1
        else:
            novote.append(f)
    tordola = [f for f in novote if (contact.get(first_att[f][0][4]) or "").find("dolas422") >= 0]
    print("C9 flagged in consensus", fc, "flagged in vote", fvote, "never in vote", len(novote),
          "family", len(set(novote) & fam), "TorDola", len(tordola))

    # C10 family restarts 10-01
    lo = common.ts_epoch("2026-10-01 15:36:30")
    hi = common.ts_epoch("2026-10-01 15:47:53")
    rs = c.execute("select fp, address, boot from restart where boot_epoch between ? and ?", (lo - 3, hi + 3)).fetchall()
    rs = [r for r in rs if r[0] in fam]
    fam_hosts_victim = {first_att[f][0][2] for f in fv}
    print("C10 family restarts", len(rs), "hosts", len({r[1] for r in rs}),
          "victim hosts covered", len({r[1] for r in rs} & fam_hosts_victim), "of", len(fam_hosts_victim),
          "distinct fps", len({r[0] for r in rs}), "range", min(r[2] for r in rs), max(r[2] for r in rs))
    miss = fam_hosts_victim - {r[1] for r in rs}
    for h in miss:
        fps = [f for f in fv if first_att[f][0][2] == h]
        for f in fps:
            ds = descs[f]
            print("   missing host", h, f, "first desc in DB", ds[0][0],
                  "descs before 10-01 15:48", sum(1 for d in ds if d[0] < "2026-10-01 15:48:00"))

    # C11
    nc = [f for f in victims if op(f).startswith("nocontact")]
    print("C11 no-contact victims", len(nc), "hosts", len({first_att[f][0][2] for f in nc}))

    # C12
    rows = c.execute("select distinct fp from cons_entry where va between '2026-10-05 17:00:00' and "
                     "'2026-10-07 02:00:00'").fetchall()
    lv = sorted({r[0] for r in rows} & vset)
    print("C12 victims listed 10-05 17:00..10-07 02:00:", len(lv), lv[:12])
    for f in lv:
        last = c.execute("select max(va), policy from cons_entry where fp=? and va between '2026-10-05 17:00:00' and "
                         "'2026-10-07 02:00:00'", (f,)).fetchone()
        print("   ", f, vic[f]["nickname"], last)

    # C13/C14 reference consensus
    ref = c.execute("select fp, ip from cons_entry where va=?", (REF_VA,)).fetchall()
    fam_as = {"36352", "197540", "141995", "51167", "211619", "40021"}
    nf_on = [(f, ip) for f, ip in ref if f not in fam and asn.get(ip) in fam_as]
    print("C13 non-family relays on 6 family ASes at", REF_VA, len(nf_on), "hit", sum(1 for f, _ in nf_on if f in vset))
    nf_ref = [(f, ip) for f, ip in ref if f not in fam]
    a = [(f, ip) for f, ip in nf_ref if asn.get(ip) == FRANTECH]
    b = [(f, ip) for f, ip in nf_ref if asn.get(ip) != FRANTECH]
    print("C14 non-family FranTech", sum(1 for f, _ in a if f in vset), "/", len(a),
          "other", sum(1 for f, _ in b if f in vset), "/", len(b), "relays in ref", len(ref))


if __name__ == "__main__":
    main()
