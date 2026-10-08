"""email_crit1_checks.py - spot-checks for critique round 1 of the tor-relays reply draft.

Re-derives, from net/netdb.sqlite (read-only) and net/victims.csv, the draft's numbers that
the research JSON does not state directly or that a reader could misread:
  pre       9CDB4020 flags history (cons_interval) - "BadExit since 08-17"
  listed    victims listed in each consensus 2026-10-05 17:00 .. 2026-10-07 02:00
  revert    10-02 09:29:25-09:44:12 non-family transitions; OUR_POLICY -> other: same hash as
            the policy before 10-01?
  usable    usable attacker exits 2026-10-05 10:00 .. 17:00 (attacker p line, Exit, no BadExit)
  novote    victims never BadExit/MiddleOnly in any vote: family / TorDola split
  fam1001   family hosts restarted 2026-10-01 15:36:30-15:47:53 vs family victim hosts
  nonexit   victims whose class before the first attacker descriptor was non-exit; Exit flag later?
  nocontact victims without a contact line and their hosts
  votes     vote table range and per-authority first flag on a victim (excl. 9CDB4020)
  rollback  10-04 22:21:18-22:47:33 policy moves (hash equal to the policy two steps back)
  cons      consensus totals 10-05 11:00 / 12:00
  uniq      unique pre-10-01 descriptor digests: DB plus *.digests files given on the command line
Standard library only; run as "python3 -I scripts/email_crit1_checks.py SECTION [args]".
"""
import collections
import csv
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "net", "netdb.sqlite")
VICT = os.path.join(ROOT, "net", "victims.csv")
SEEDS = os.path.join(ROOT, "family_seed_fingerprints.txt")
NEAR = "reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999"
OURP = "reject 25,110,135,137-139,143,445,465,587,993,995,3389"
ATT = (NEAR, OURP)
PRE = "9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76"


def conn():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def victims():
    with open(VICT, newline="") as fh:
        return {r["fp"]: r for r in csv.DictReader(fh)}


def sec_pre(db):
    for r in db.execute("select start_va,end_va,flags,policy from cons_interval where fp=? "
                        "order by start_va", (PRE,)):
        print(r)


def sec_listed(db):
    V = victims()
    vas = [r[0] for r in db.execute("select va from consensus where va>='2026-10-05 16:00:00' "
                                    "order by va")]
    seen = collections.Counter()
    for va in vas:
        fps = [r for r in db.execute("select fp,flags,policy from cons_entry where va=?", (va,))
               if r[0] in V]
        for fp, _, _ in fps:
            seen[fp] += 1
        print(va, "victims listed", len(fps),
              "attacker p", sum(1 for r in fps if r[2] in ATT))
    print("distinct victims listed 10-05 17:00+ (excluding 16:00):")
    s2 = collections.Counter()
    for va in vas:
        if va < "2026-10-05 17:00:00":
            continue
        for (fp,) in db.execute("select fp from cons_entry where va=?", (va,)):
            if fp in V:
                s2[fp] += 1
    for fp, n in s2.most_common():
        print(" ", fp, V[fp]["nickname"], V[fp]["family"], n)


def pol_seq(db, fp):
    return list(db.execute("select d.published,d.policy_h,p.class,p.summary,d.boot_epoch from "
                           "descriptor d join policy p using(policy_h) where d.fp=? "
                           "order by d.published", (fp,)))


def sec_revert(db):
    V = victims()
    rows = list(db.execute("select fp,published,old_class,new_class,old_h,new_h,kind from "
                           "policy_event where published between '2026-10-02 09:29:25' and "
                           "'2026-10-02 09:44:12' order by published"))
    nf = [r for r in rows if r[0] in V and V[r[0]]["family"] == "0"]
    print("policy_event rows non-family victims", len(nf), "distinct fp", len({r[0] for r in nf}))
    c = collections.Counter((r[2], r[3]) for r in nf)
    print(c)
    for fp, pub, oc, nc, oh, nh, kind in nf:
        if oc == "OUR_POLICY" and nc not in ("near-open", "OUR_POLICY"):
            seq = pol_seq(db, fp)
            pre = [s for s in seq if s[0] < "2026-10-01 14:49:51"]
            last_pre_h = pre[-1][1] if pre else None
            print(" ", fp, V[fp]["nickname"], pub, nc, kind, "same as last pre-10-01 hash:",
                  nh == last_pre_h)
    # also non-victim non-family relays changing in window? (for 39 count)
    allnf = {r[0] for r in rows if (r[0] not in V or V[r[0]]["family"] == "0")}
    print("all non-family fps with policy_event in window", len(allnf))


def sec_usable(db):
    V = victims()
    for va in [r[0] for r in db.execute("select va from consensus where va between "
                                        "'2026-10-05 10:00:00' and '2026-10-05 17:00:00' "
                                        "order by va")]:
        tot = 0
        n = 0
        bw = 0
        att_n = 0
        flagged = 0
        for fp, flags, pol, b in db.execute("select fp,flags,policy,bw from cons_entry where va=?",
                                            (va,)):
            fl = set((flags or "").split())
            if "Exit" in fl and "BadExit" not in fl:
                tot += b or 0
            if pol in ATT:
                att_n += 1
                if fl & {"BadExit", "MiddleOnly"}:
                    flagged += 1
                if "Exit" in fl and "BadExit" not in fl:
                    n += 1
                    bw += b or 0
        print(va, "attacker p", att_n, "flagged", flagged, "usable", n,
              "%.3f%%" % (100.0 * bw / tot if tot else 0))


def sec_novote(db):
    V = victims()
    flagged = set()
    for fp, flags in db.execute("select fp,flags from vote_entry where flags like '%BadExit%' "
                                "or flags like '%MiddleOnly%'"):
        if fp in V:
            flagged.add(fp)
    nv = [fp for fp in V if fp not in flagged]
    print("flagged in >=1 vote", len(flagged), "never", len(nv))
    print("never: family", sum(1 for fp in nv if V[fp]["family"] == "1"))
    print("never by operator/AS:", collections.Counter((V[fp]["as_name"], V[fp]["nickname"][:6])
                                                       for fp in nv if V[fp]["family"] == "0"))
    td = [fp for fp in nv if V[fp]["nickname"].startswith("TorDola")]
    print("never TorDola", len(td), td)
    # consensus-flagged after first attacker desc
    cf = set()
    for fp, va, flags in db.execute("select fp,va,flags from cons_entry where flags like "
                                    "'%BadExit%' or flags like '%MiddleOnly%'"):
        if fp in V and va >= V[fp]["first_attacker_desc"][:13] + ":00:00":
            cf.add(fp)
    print("consensus-flagged (va >= hour of first attacker desc)", len(cf))


def sec_fam1001(db):
    V = victims()
    fam = {fp for fp in V if V[fp]["family"] == "1"}
    famhosts = {V[fp]["ip"] for fp in fam}
    r = list(db.execute("select fp,boot,address,first_published from restart where boot between "
                        "'2026-10-01 15:36:00' and '2026-10-01 15:48:30'"))
    rf = [x for x in r if x[0] in fam]
    print("family victim restarts", len(rf), "hosts", len({x[2] for x in rf}),
          "min", min(x[1] for x in rf), "max", max(x[1] for x in rf))
    # all family fps (seeds + contact prefix)
    seeds = {l.strip().upper() for l in open(SEEDS) if l.strip()}
    rfa = [x for x in r if x[0] in seeds or x[0] in fam]
    print("restarts by fam victims or seeds", len(rfa), "hosts", len({x[2] for x in rfa}))
    missing = famhosts - {x[2] for x in rf}
    print("victim family hosts:", len(famhosts), "not restarted:", missing)
    for h in missing:
        for row in db.execute("select fp,min(published),max(published),count(*) from descriptor "
                              "where address=? group by fp", (h,)):
            print("  ", h, row)
    # active family hosts at 10-01 14:00 consensus
    act = {ip for fp, ip in db.execute("select fp,ip from cons_entry where va='2026-10-01 14:00:00'")
           if fp in fam}
    print("family victim hosts in 10-01 14:00 consensus", len(act))


def sec_nonexit(db):
    V = victims()
    ne = [fp for fp in V if V[fp]["class_before_first_attacker_desc"] == "non-exit"]
    print("non-exit before:", len(ne), "family", sum(1 for fp in ne if V[fp]["family"] == "1"))
    print(collections.Counter(V[fp]["class_before_first_attacker_desc"] for fp in V))
    got = 0
    for fp in ne:
        r = db.execute("select min(va) from cons_entry where fp=? and flags like '%Exit%' and "
                       "(' '||flags||' ') like '% Exit %' and va>=?",
                       (fp, V[fp]["first_attacker_desc"][:13] + ":00:00")).fetchone()
        if r[0]:
            got += 1
        else:
            print("  no Exit:", fp, V[fp]["nickname"])
    print("non-exits that got Exit in a consensus:", got)


def sec_nocontact(db):
    V = victims()
    nc = [fp for fp in V if not V[fp]["operator"]]
    print("no contact", len(nc), "hosts", len({V[fp]["ip"] for fp in nc}),
          [(V[fp]["nickname"], V[fp]["ip"]) for fp in nc])
    print("operators", len({V[fp]["operator"] for fp in V if V[fp]["operator"]}) + len(nc))
    print("hosts", len({V[fp]["ip"] for fp in V}), "ASes", len({V[fp]["asn"] for fp in V}))


def sec_votes(db):
    print(db.execute("select min(va),max(va),count(distinct va) from vote").fetchone())
    V = victims()
    first = {}
    for va, auth, fp, flags in db.execute("select va,auth,fp,flags from vote_entry where "
                                          "(flags like '%BadExit%' or flags like '%MiddleOnly%') "
                                          "order by va"):
        if fp in V and fp != PRE and auth not in first:
            first[auth] = (va, flags)
    for a, v in sorted(first.items(), key=lambda x: x[1][0]):
        print(a, v)


def sec_rollback(db):
    V = victims()
    rows = list(db.execute("select fp,published,old_h,new_h,old_class,new_class,kind from "
                           "policy_event where published between '2026-10-04 22:21:18' and "
                           "'2026-10-04 22:47:33' order by published"))
    print("events", len(rows), collections.Counter((r[4], r[5], r[6]) for r in rows))
    same = 0
    for fp, pub, oh, nh, oc, nc, kind in rows:
        seq = [s for s in pol_seq(db, fp) if s[0] < pub]
        hs = []
        for s in seq:
            if not hs or hs[-1] != s[1]:
                hs.append(s[1])
        prior = hs[-2] if len(hs) >= 2 else None
        if prior == nh:
            same += 1
    print("new hash == policy before previous change:", same)
    newk = list(db.execute("select fp,min(published) from descriptor group by fp having "
                           "min(published) between '2026-10-04 22:21:18' and '2026-10-04 22:47:33'"))
    print("new keys in window", [(f, p, f in V) for f, p in newk])


def sec_cons(db):
    for va in ("2026-10-05 11:00:00", "2026-10-05 12:00:00", "2026-10-04 01:00:00"):
        c = collections.Counter()
        for flags, pol in db.execute("select flags,policy from cons_entry where va=?", (va,)):
            fl = set((flags or "").split())
            c["n"] += 1
            c["BadExit"] += "BadExit" in fl
            c["MiddleOnly"] += "MiddleOnly" in fl
            c["att"] += pol in ATT
        print(va, dict(c))


def sec_uniq(db, files):
    s = {d.upper() for (d,) in db.execute("select digest from descriptor where "
                                          "published < '2026-10-01'")}
    print("db", len(s))
    for f in files:
        with open(f) as fh:
            for line in fh:
                if line.strip():
                    s.add(line.strip().upper())
    print("union", len(s))


def main():
    db = conn()
    sec = sys.argv[1]
    if sec == "uniq":
        sec_uniq(db, sys.argv[2:])
    else:
        globals()["sec_" + sec](db)


if __name__ == "__main__":
    main()
