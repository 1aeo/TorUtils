"""email_crit3_checks.py - independent spot checks for critique round 3 of the tor-relays reply draft.

Read-only on net/netdb.sqlite (plus family_seed_fingerprints.txt); standard library only;
run as "python3 -I scripts/email_crit3_checks.py".  Queries are written from scratch (no
CSV and no earlier email_* script is read for results).  Each block prints the numbers the
draft cites:
  X1  usable attacker exit weight per consensus 10-04 00:00 .. 10-05 17:00
  X2  attacker p lines and BadExit/MiddleOnly at 10-05 11:00 and 12:00
  X3  cons_interval history of 9CDB4020 (TimberDolphin63) from 2026-08-01
  X4  family restarts 10-05 08:56:30 .. 10:39:50
  X5  victim transitions to an attacker class 10-02 09:44:13 .. 23:59:59 and on 10-03
  X6  10-04 22:21:18 .. 22:47:33 policy moves, byte-exact check
  X7  TorDola policy texts 09-20 .. 10-01 14:51 (7-rule ordered prefix)
  X8  operators (exact contact; no contact = per relay) with / without any FranTech descriptor
  X9  ip_as CAIDA/IPFire agreement on victim IPs
  X10 first vote per authority with BadExit/MiddleOnly on a victim (excl. 9CDB4020)
  X11 FranTech-hit non-family operators: their non-FranTech relays at 10-01 14:00
  X12 victims ever BadExit/MiddleOnly in a consensus after first attacker descriptor; in any vote
  X13 non-exit victims (class before first attacker descriptor) and Exit flag afterwards
  X14 family restarts 10-01 15:36:30 .. 15:47:53 (hosts vs family victim hosts)
  X15 attacker p lines in DB consensuses 10-05 16:00 .. 10-07 02:00
  X16 non-family relays on the family's non-FranTech ASes at 10-01 14:00

Missing ContactInfo is stored as contact_h "-"; such relays count as one operator each.
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "net", "netdb.sqlite")
NEAR = "reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999"
OURP = "reject 25,110,135,137-139,143,445,465,587,993,995,3389"
ATT = (NEAR, OURP)
FAM_PREFIX = "email:Quetzalcoatl_relays[]proton.me"
PRE = "9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76"


def main():
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    victims = {r[0] for r in c.execute("select fp from victim")}
    seeds = {l.strip().upper() for l in open(os.path.join(ROOT, "family_seed_fingerprints.txt"))
             if l.strip() and not l.startswith("#")}
    fam = set(seeds)
    for (fp,) in c.execute("select distinct d.fp from descriptor d join contact k on "
                           "k.contact_h=d.contact_h where k.text like ?", (FAM_PREFIX + "%",)):
        fam.add(fp)
    print("victims", len(victims), "family fps", len(fam), "family victims", len(victims & fam))

    # X1
    print("X1 usable attacker exits")
    vas = [r[0] for r in c.execute("select va from consensus where va between "
                                   "'2026-10-04 00:00:00' and '2026-10-05 17:00:00' order by va")]
    for va in vas:
        tot = 0
        att = 0
        n = 0
        for fp, flags, bw, pol in c.execute("select fp,flags,bw,policy from cons_entry where va=?", (va,)):
            fl = set((flags or "").split())
            if "Exit" in fl and "BadExit" not in fl:
                tot += bw or 0
                if fp in victims and pol in ATT:
                    att += bw or 0
                    n += 1
        print("  ", va, n, att, tot, "%.4f%%" % (100.0 * att / tot if tot else 0))

    # X2
    for va in ("2026-10-05 11:00:00", "2026-10-05 12:00:00"):
        rows = c.execute("select fp,flags,policy from cons_entry where va=?", (va,)).fetchall()
        attp = [r for r in rows if r[2] in ATT]
        be = sum(1 for r in attp if "BadExit" in r[1].split())
        mo = sum(1 for r in attp if "MiddleOnly" in r[1].split())
        either = sum(1 for r in attp if {"BadExit", "MiddleOnly"} & set(r[1].split()))
        tbe = sum(1 for r in rows if "BadExit" in r[1].split())
        tmo = sum(1 for r in rows if "MiddleOnly" in r[1].split())
        nonvict = sum(1 for r in attp if r[0] not in victims)
        print("X2", va, "attacker p", len(attp), "BadExit", be, "MiddleOnly", mo, "either", either,
              "totals", tbe, tmo, "non-victim attacker p", nonvict)

    # X3
    print("X3 9CDB4020 intervals from 2026-08-01")
    for r in c.execute("select start_va,end_va,n,flags,policy,after_gap from cons_interval where fp=? "
                       "and end_va>='2026-08-01' order by start_va", (PRE,)):
        print("  ", r)

    # X4
    rows = c.execute("select fp,boot,address from restart where boot between '2026-10-05 08:56:30' "
                     "and '2026-10-05 10:39:50'").fetchall()
    fr = [r for r in rows if r[0] in fam]
    print("X4 family restarts", len({r[0] for r in fr}), "hosts", len({r[2] for r in fr}),
          "min", min(r[1] for r in fr), "max", max(r[1] for r in fr),
          "non-family restarts in window", len([r for r in rows if r[0] not in fam]))

    # X5
    def transitions(lo, hi):
        out = []
        for r in c.execute("select fp,published,nickname,address,old_class,new_class,new_summary,kind "
                           "from policy_event where published between ? and ? order by published",
                           (lo, hi)):
            if r[0] in victims and r[6] in ATT and r[4] not in ("near-open", "OUR_POLICY") \
                    and not (r[4] is None and r[7] != "first"):
                out.append(r)
        return out
    ipas = {r[0]: r[1] for r in c.execute("select ip,asn from ip_as")}
    t = transitions("2026-10-02 09:44:13", "2026-10-02 23:59:59")
    print("X5a 10-02 after 09:44:12 into attacker class:", len(t),
          collections.Counter(ipas.get(r[3]) for r in t), collections.Counter(r[7] for r in t))
    for r in t:
        print("   ", r[1], r[0], r[2], r[4], r[7], ipas.get(r[3]))
    t = transitions("2026-10-03 00:00:00", "2026-10-03 23:59:59")
    print("X5b 10-03 into attacker class:", len(t),
          collections.Counter((r[4], r[7]) for r in t), "ASes", sorted({ipas.get(r[3]) for r in t}))
    for r in t:
        print("   ", r[1], r[0], r[2], r[4], r[7], ipas.get(r[3]))
    allev = c.execute("select fp,published,old_class,new_class,new_summary,kind from policy_event "
                      "where published between '2026-10-03 00:00:00' and '2026-10-03 23:59:59' "
                      "and new_summary in (?,?)", ATT).fetchall()
    print("    all 10-03 events with attacker new summary:", len(allev),
          collections.Counter((r[2], r[5]) for r in allev))

    # X6
    ev = c.execute("select fp,published,old_h,new_h,old_class,new_class,kind from policy_event where "
                   "published between '2026-10-04 22:21:18' and '2026-10-04 22:47:33' order by published"
                   ).fetchall()
    exact = 0
    to_our = 0
    for fp, pub, old_h, new_h, oc, nc, kind in ev:
        hist = [r[0] for r in c.execute("select new_h from policy_event where fp=? and published<? "
                                        "order by published", (fp, pub))]
        # policy before the previous change = new_h of the event before the last one
        prev = hist[-2] if len(hist) >= 2 else None
        if prev == new_h:
            exact += 1
        if nc == "OUR_POLICY":
            to_our += 1
    print("X6 events", len(ev), "kinds", collections.Counter(r[6] for r in ev),
          "byte-exact to pre-previous", exact, "to OUR_POLICY", to_our,
          collections.Counter((r[4], r[5]) for r in ev))

    # X7
    tordola = ("4F72DEF09B015E9B6F210597083D95D8A3BC38AD", "15CA183DC161A0AF6FACDD7A0B6DA84C593E8D09",
               "8B2CCF2A27D52CEE3DC055C1AD11E3755104F601", "C6AA7656909FA64A03EFBA40DD294D4BD79AA3E0")
    pref = ["reject *:25", "reject *:465", "reject *:587", "reject *:110", "reject *:143",
            "reject *:993", "reject *:995"]
    first = {}
    n7 = 0
    for fp, pub, text in c.execute(
            "select d.fp,d.published,p.text from descriptor d join policy p on p.policy_h=d.policy_h "
            "where d.fp in (?,?,?,?) and d.published between '2026-08-25' and '2026-10-01 14:49:50' "
            "order by d.published", tordola):
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith("reject *:")]
        if lines[:7] == pref:
            n7 += 1
            first.setdefault(fp, pub)
    print("X7 TorDola 7-rule prefix descriptors", n7, "first per fp", first)
    # any other relay with that prefix before 10-01 14:49:51
    others = set()
    for ph, text in c.execute("select policy_h,text from policy"):
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith("reject *:")]
        if lines[:7] == pref:
            for (fp,) in c.execute("select distinct fp from descriptor where policy_h=? and "
                                   "published<'2026-10-01 14:49:51'", (ph,)):
                others.add(fp)
    print("    fps with prefix before 14:49:51:", sorted(others))

    # X8
    # operator of each victim: contact on its first attacker descriptor
    vop = {}
    vasn = {}
    for fp in victims:
        r = c.execute("select d.contact_h,d.address from descriptor d join policy p on "
                      "p.policy_h=d.policy_h where d.fp=? and p.summary in (?,?) order by d.pub_epoch "
                      "limit 1", (fp, NEAR, OURP)).fetchone()
        vop[fp] = r[0] if r[0] and r[0] != "-" else "nocontact:" + fp
        vasn[fp] = ipas.get(r[1])
    ops = collections.defaultdict(set)
    for fp, op in vop.items():
        ops[op].add(fp)
    fran_ops = set()
    for op in ops:
        if op.startswith("nocontact:"):
            fps = [op.split(":", 1)[1]]
            q = "select distinct address from descriptor where fp=?"
            addrs = {r[0] for r in c.execute(q, fps)}
        else:
            addrs = {r[0] for r in c.execute("select distinct address from descriptor where contact_h=?",
                                             (op,))}
        if any(ipas.get(a) == "53667" for a in addrs):
            fran_ops.add(op)
    nof = [op for op in ops if op not in fran_ops]
    nof_relays = set().union(*[ops[o] for o in nof])
    print("X8 operators", len(ops), "with FranTech", len(fran_ops), "without", len(nof),
          "their victims", len(nof_relays), "ASes", sorted({vasn[f] for f in nof_relays}),
          "hosts", len({c.execute("select address from descriptor where fp=? limit 1", (f,)).fetchone()[0]
                        for f in nof_relays}))
    vip = {}
    for fp in victims:
        vip[fp] = c.execute("select d.address from descriptor d join policy p on p.policy_h=d.policy_h "
                            "where d.fp=? and p.summary in (?,?) order by d.pub_epoch limit 1",
                            (fp, NEAR, OURP)).fetchone()[0]

    # X9
    ips = set(vip.values())
    ag = [c.execute("select agree,asn,ipfire_asn from ip_as where ip=?", (ip,)).fetchone() for ip in ips]
    print("X9 victim IPs", len(ips), "found", sum(1 for a in ag if a), "agree",
          sum(1 for a in ag if a and a[0] == 1), "asn==ipfire", sum(1 for a in ag if a and a[1] == a[2]))

    # X10
    first_auth = {}
    maxes = collections.Counter()
    per_va = collections.defaultdict(set)
    for va, auth, fp, flags in c.execute("select va,auth,fp,flags from vote_entry where "
                                         "(flags like '%BadExit%' or flags like '%MiddleOnly%')"):
        if fp in victims and fp != PRE:
            per_va[(auth, va)].add(fp)
            if auth not in first_auth or va < first_auth[auth][0]:
                first_auth[auth] = (va, flags)
    for (auth, va), s in per_va.items():
        maxes[auth] = max(maxes[auth], len(s))
    for auth in sorted(first_auth, key=lambda a: first_auth[a][0]):
        print("X10", auth, first_auth[auth][0], "max victims flagged", maxes[auth])

    # X11
    ref = "2026-10-01 14:00:00"
    opref = collections.defaultdict(list)
    for fp, ip, dig in c.execute("select fp,ip,digest from cons_entry where va=?", (ref,)):
        r = c.execute("select contact_h from descriptor where digest=?", (dig,)).fetchone()
        if r is None:
            r = c.execute("select contact_h from descriptor where fp=? and published<=? order by pub_epoch "
                          "desc limit 1", (fp, ref)).fetchone()
        ch = r[0] if r and r[0] and r[0] != "-" else "nocontact:" + fp
        opref[ch].append((fp, ip))
    nfvict_ops = {vop[f] for f in victims if f not in fam and vasn[f] == "53667"}
    k = 0
    rel = 0
    hit = 0
    ases = set()
    for op in nfvict_ops:
        else_rel = [(fp, ip) for fp, ip in opref.get(op, []) if ipas.get(ip) != "53667"]
        if else_rel:
            k += 1
            rel += len(else_rel)
            hit += sum(1 for fp, _ in else_rel if fp in victims)
            ases |= {ipas.get(ip) for _, ip in else_rel}
    for op in sorted(nfvict_ops):
        else_rel = [(fp, ip) for fp, ip in opref.get(op, []) if ipas.get(ip) != "53667"]
        if else_rel:
            print("    op", op[:12], "elsewhere", len(else_rel), "hit", sum(1 for fp, _ in else_rel if fp in victims))
    print("X11 FranTech-hit non-family operators", len(nfvict_ops), "with relays elsewhere at ref", k,
          "relays", rel, "hit", hit, "ASes", len(ases))

    # X12
    first_att = {}
    for fp in victims:
        first_att[fp] = c.execute("select min(d.published) from descriptor d join policy p on "
                                  "p.policy_h=d.policy_h where d.fp=? and p.summary in (?,?)",
                                  (fp, NEAR, OURP)).fetchone()[0]
    in_cons = set()
    for fp in victims:
        for va, flags in c.execute("select va,flags from cons_entry where fp=? and va>=?",
                                   (fp, first_att[fp][:13] + ":00:00")):
            if {"BadExit", "MiddleOnly"} & set(flags.split()) and va >= first_att[fp]:
                in_cons.add(fp)
                break
    # cons_entry starts 2026-09-24; all first attacker descriptors are in October
    in_vote = set()
    for fp in victims:
        r = c.execute("select 1 from vote_entry where fp=? and (flags like '%BadExit%' or "
                      "flags like '%MiddleOnly%') limit 1", (fp,)).fetchone()
        if r:
            in_vote.add(fp)
    nov = victims - in_vote
    tordola_ops = {vop[f] for f in ("4F72DEF09B015E9B6F210597083D95D8A3BC38AD",)}
    print("X12 flagged in consensus", len(in_cons), "in vote", len(in_vote), "never in vote", len(nov),
          "family", len(nov & fam), "TorDola-contact", sum(1 for f in nov if vop[f] in tordola_ops),
          "min first_att", min(first_att.values()))

    # X13
    nonexit = []
    for fp in victims:
        r = c.execute("select p.class from descriptor d join policy p on p.policy_h=d.policy_h where "
                      "d.fp=? and d.published<? order by d.pub_epoch desc limit 1",
                      (fp, first_att[fp])).fetchone()
        if r and r[0] == "non-exit":
            nonexit.append(fp)
    gotexit = [fp for fp in nonexit if c.execute(
        "select 1 from cons_entry where fp=? and va>=? and (' '||flags||' ') like '% Exit %' limit 1",
        (fp, first_att[fp][:10])).fetchone()]
    print("X13 non-exit victims", len(nonexit), "family", len(set(nonexit) & fam), "got Exit", len(gotexit))

    # X14
    rows = c.execute("select fp,address from restart where boot between '2026-10-01 15:36:30' and "
                     "'2026-10-01 15:47:53'").fetchall()
    fr = [r for r in rows if r[0] in fam]
    famhosts = {vip[f] for f in victims & fam}
    print("X14 family restarts fps", len({r[0] for r in fr}), "hosts", len({r[1] for r in fr}),
          "of family victim hosts", len(famhosts), "covered", len({r[1] for r in fr} & famhosts))

    # X15
    n = c.execute("select count(*), count(distinct va), min(va), max(va) from cons_entry where va>="
                  "'2026-10-05 16:00:00' and policy in (?,?)", ATT).fetchone()
    nva = c.execute("select count(*) from consensus where va between '2026-10-05 17:00:00' and "
                    "'2026-10-07 02:00:00'").fetchone()[0]
    print("X15 attacker p entries from 10-05 16:00:", n, "consensuses 10-05 17:00..10-07 02:00:", nva)

    # X16
    famas = {vasn[f] for f in victims & fam} - {"53667"}
    tot = 0
    hit = 0
    for fp, ip in c.execute("select fp,ip from cons_entry where va=?", (ref,)):
        if fp not in fam and ipas.get(ip) in famas:
            tot += 1
            hit += fp in victims
    print("X16 family ASes", sorted(famas), "non-family relays", tot, "hit", hit)


if __name__ == "__main__":
    main()
