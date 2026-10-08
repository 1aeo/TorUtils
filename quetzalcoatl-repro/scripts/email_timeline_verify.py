#!/usr/bin/env python3
"""email_timeline_verify.py - re-derive, second by second, every event of the incident timeline used in
the tor-relays email draft, from net/netdb.sqlite and the net/ + out/ CSVs (standard library only).

It deliberately avoids the derived DB tables policy_event / victim / restart / reload:
  * every policy text in table `policy` is re-summarized with common.summarize_policy() and classed
    near-open / OUR_POLICY from the recomputed summary (mismatches with policy.summary are counted);
  * victims and attacker-class transitions are recomputed from raw `descriptor` rows ordered by
    pub_epoch; restart vs reload uses the derive_tables.py boot rule (boot = published - uptime;
    |delta| <= 2 s = same boot; a new boot >= previous publication = restart, otherwise drift);
  * the OUR_POLICY ordered rule sequence is matched on the raw policy text lines;
  * family = the seeds in family_seed_fingerprints.txt + relays whose contact starts with
    "email:Quetzalcoatl_relays[]proton.me"; operator = exact contact string (no contact = own operator);
  * AS = CAIDA mapping in table ip_as (FranTech = AS53667).
Then it cross-checks the CSVs (waves, rollback, sweep, votes, exposure).

Sections: E1 first OUR_POLICY + precursor checks; WAVES (15-min chaining); E2 10-01 wave; E3 first
near-open + 10-02 wave; E4 later flips and new identity keys; E5 authority votes, consensus flags, last
attacker p line; E6 rollback; E7 family sweep 10-05; E8 end state; X exit-weight exposure.

Usage: python3 -I scripts/email_timeline_verify.py [--db net/netdb.sqlite] > net/email_timeline_verify.log
"""
import argparse
import ast
import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import NEAR_OPEN, OUR_POLICY, summarize_policy, epoch_ts, ts_epoch  # noqa: E402

ROOT = os.path.dirname(HERE)
FAM_PREFIX = "email:Quetzalcoatl_relays[]proton.me"
OUR_SEQ = ["25", "465", "587", "110", "143", "993", "995", "3389", "135", "137-139", "445"]
ATT = {NEAR_OPEN: "near-open", OUR_POLICY: "OUR_POLICY"}


def p(*a):
    print(*a, flush=True)


def wild_rejects(text):
    """ports of 'reject *:PORT' lines, in order (own-IP / private-net lines are not wildcards)."""
    out = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if ln.startswith("reject *:"):
            out.append(ln[len("reject *:"):])
    return out


def contains_contig(seq, sub):
    n = len(sub)
    return any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def contains_subseq(seq, sub):
    it = iter(seq)
    return all(any(x == s for x in it) for s in sub)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(ROOT, "net", "netdb.sqlite"))
    args = ap.parse_args()
    db = sqlite3.connect(args.db)

    # ------------------------------------------------------------------ policies
    pol_cls, pol_text = {}, {}
    mism = 0
    for h, text, summ in db.execute("SELECT policy_h, text, summary FROM policy"):
        s = summarize_policy([x for x in text.split("\n") if x.strip()])
        if s != summ:
            mism += 1
        pol_cls[h] = ATT.get(s, "other")
        pol_text[h] = text
    att_h = {h for h, c in pol_cls.items() if c != "other"}
    p("POLICIES: %d texts re-summarized; mismatches with stored summary: %d; near-open texts %d, OUR_POLICY texts %d"
      % (len(pol_cls), mism, sum(c == "near-open" for c in pol_cls.values()),
         sum(c == "OUR_POLICY" for c in pol_cls.values())))
    seq_contig = {h for h, t in pol_text.items() if contains_contig(wild_rejects(t), OUR_SEQ)}
    seq_subseq = {h for h, t in pol_text.items() if contains_subseq(wild_rejects(t), OUR_SEQ)}
    pre8 = OUR_SEQ[:8]
    seq_pre8 = {h for h, t in pol_text.items() if contains_contig(wild_rejects(t), pre8)}
    p("OUR_SEQ contiguous in %d texts (classes %s); as ordered subsequence in %d texts (classes %s)"
      % (len(seq_contig), dict(Counter(pol_cls[h] for h in seq_contig)), len(seq_subseq),
         dict(Counter(pol_cls[h] for h in seq_subseq))))

    contact = {h: t for h, t in db.execute("SELECT contact_h, text FROM contact")}
    ipas = {ip: (asn, asname) for ip, asn, asname in db.execute("SELECT ip, asn, as_name FROM ip_as")}
    seeds = set()
    for line in open(os.path.join(ROOT, "family_seed_fingerprints.txt")):
        t = line.split("#")[0].strip().upper()
        if len(t) == 40:
            seeds.add(t)
    fam_contact_h = {h for h, t in contact.items() if t and t.startswith(FAM_PREFIX)}
    fam = set(seeds)
    for (fp,) in db.execute("SELECT DISTINCT fp FROM descriptor WHERE contact_h IN (%s)"
                            % ",".join("?" * len(fam_contact_h)), list(fam_contact_h)):
        fam.add(fp)
    p("FAMILY: %d seeds, %d contact hashes with prefix, %d fingerprints total" % (len(seeds), len(fam_contact_h), len(fam)))

    def asn(ip):
        return ipas.get(ip, ("?", "?"))

    def oper(fp, ch):
        return contact.get(ch) if ch and contact.get(ch) else "(no contact) " + fp

    # ------------------------------------------------------------------ E1
    p("\n=== E1 first OUR_POLICY / near-open descriptor; precursor checks")
    our_hs = [h for h, c in pol_cls.items() if c == "OUR_POLICY"]
    near_hs = [h for h, c in pol_cls.items() if c == "near-open"]

    def first_desc(hs):
        q = ("SELECT published, pub_epoch, fp, nickname, address, contact_h, digest, policy_h FROM descriptor "
             "WHERE policy_h IN (%s) ORDER BY pub_epoch, fp LIMIT 5" % ",".join("?" * len(hs)))
        return db.execute(q, hs).fetchall()
    fo = first_desc(our_hs)
    fn = first_desc(near_hs)
    for lab, rows in (("OUR_POLICY", fo), ("near-open", fn)):
        for r in rows:
            p("  first %s: %s %s %s %s %s contact=%r digest=%s" % (lab, r[0], r[2], r[3], r[4], asn(r[4]),
                                                                  contact.get(r[5]), r[6]))
    t_our = fo[0][1]
    allatt = our_hs + near_hs
    n_before = db.execute("SELECT count(*) FROM descriptor WHERE pub_epoch < ? AND policy_h IN (%s)"
                          % ",".join("?" * len(allatt)), [t_our] + allatt).fetchone()[0]
    sq = list(seq_subseq)
    n_seq_before = db.execute("SELECT count(*) FROM descriptor WHERE pub_epoch < ? AND policy_h IN (%s)"
                              % ",".join("?" * len(sq)), [t_our] + sq).fetchone()[0]
    first_seq = db.execute("SELECT published, fp, nickname FROM descriptor WHERE policy_h IN (%s) ORDER BY pub_epoch LIMIT 1"
                           % ",".join("?" * len(sq)), sq).fetchone()
    tot = db.execute("SELECT count(*), min(published) FROM descriptor WHERE pub_epoch < ?", [t_our]).fetchone()
    p("  descriptors in DB before %s: %d (earliest %s); of them attacker-class: %d; containing OUR_SEQ (subseq): %d"
      % (epoch_ts(t_our), tot[0], tot[1], n_before, n_seq_before))
    p("  first descriptor containing OUR_SEQ: %s" % (first_seq,))
    p8 = list(seq_pre8)
    r8 = db.execute("SELECT published, fp, nickname, address FROM descriptor WHERE policy_h IN (%s) ORDER BY pub_epoch LIMIT 1"
                    % ",".join("?" * len(p8)), p8).fetchone()
    p("  8-rule prefix %s: %d texts, first descriptor %s" % (",".join(pre8), len(p8), r8))
    for k in range(4, 12):
        hk = [h for h, t in pol_text.items() if contains_contig(wild_rejects(t), OUR_SEQ[:k])]
        rk = db.execute("SELECT published, fp, nickname, address FROM descriptor WHERE policy_h IN (%s) ORDER BY pub_epoch LIMIT 1"
                        % ",".join("?" * len(hk)), hk).fetchone()
        nb = db.execute("SELECT count(*), count(DISTINCT fp), group_concat(DISTINCT nickname) FROM descriptor WHERE pub_epoch < ? AND policy_h IN (%s)"
                        % ",".join("?" * len(hk)), [t_our] + hk).fetchone()
        p("  first %2d rules of OUR_SEQ (contiguous, in order): first %s; before %s: %d descriptors / %d relays (%s)"
          % (k, rk, epoch_ts(t_our), nb[0], nb[1], nb[2]))
    # consensus-side check, whole window (cons_interval policy = consensus p line)
    for lab, s in (("OUR_POLICY", OUR_POLICY), ("near-open", NEAR_OPEN)):
        r = db.execute("SELECT min(start_va), max(end_va), count(DISTINCT fp) FROM cons_interval WHERE policy=?", [s]).fetchone()
        p("  consensus p line %s: first va %s, last va %s, relays %s (cons_interval, May-Oct)" % (lab, r[0], r[1], r[2]))

    # ------------------------------------------------------------------ transitions from raw descriptors
    vict = sorted({fp for (fp,) in db.execute("SELECT DISTINCT fp FROM descriptor WHERE policy_h IN (%s)"
                                                % ",".join("?" * len(allatt)), allatt)})
    vset = set(vict)
    stored_v = {fp for (fp,) in db.execute("SELECT fp FROM victim")}
    p("\nVICTIMS recomputed: %d (family %d, non-family %d); equals stored victim table: %s"
      % (len(vict), len(vset & fam), len(vset - fam), vset == stored_v))
    ev = []        # transitions
    descs = {}     # fp -> list of rows
    first_att = {}
    for fp in vict:
        rows = db.execute("SELECT published, pub_epoch, nickname, address, or_port, contact_h, policy_h, boot_epoch "
                          "FROM descriptor WHERE fp=? ORDER BY pub_epoch", [fp]).fetchall()
        descs[fp] = rows
        prev = None
        last_boot = None
        for r in rows:
            pub, pe, nick, addr, orp, ch, ph, boot = r
            c = pol_cls.get(ph, "other")
            if c != "other" and fp not in first_att:
                first_att[fp] = pe
            if prev is None:
                if c != "other":
                    ev.append(dict(t=pe, pub=pub, fp=fp, nick=nick, ip=addr, orp=orp, ch=ch, old="(first)", new=c,
                                   kind="first", newh=ph, oldh=None))
                last_boot = boot
                prev = r
                continue
            is_restart = False
            if boot is not None:
                if last_boot is None:
                    is_restart = boot >= prev[1]
                elif abs(boot - last_boot) <= 2:
                    is_restart = False
                elif boot >= prev[1]:
                    is_restart = True
                last_boot = boot
            oc = pol_cls.get(prev[6], "other")
            if ph != prev[6] and (oc != c) and (oc != "other" or c != "other"):
                ev.append(dict(t=pe, pub=pub, fp=fp, nick=nick, ip=addr, orp=orp, ch=ch, old=oc, new=c,
                               kind="restart" if is_restart else "reload", newh=ph, oldh=prev[6]))
            prev = r
    ev.sort(key=lambda e: (e["t"], e["fp"]))
    p("TRANSITIONS recomputed: %d (into %d, first %d, between %d, out %d)" % (
        len(ev), sum(e["old"] == "other" for e in ev), sum(e["kind"] == "first" for e in ev),
        sum(e["old"] in ATT.values() and e["new"] in ATT.values() for e in ev), sum(e["new"] == "other" for e in ev)))
    # cross-check attacker_transitions.csv
    csv_ev = {(r["published"], r["fp"], r["new_class"]) for r in csv.DictReader(open(os.path.join(ROOT, "net", "attacker_transitions.csv")))}
    mine = {(e["pub"], e["fp"], e["new"] if e["new"] != "other" else None) for e in ev}
    csv_norm = {(a, b, c if c in ATT.values() else None) for a, b, c in csv_ev}
    p("  vs attacker_transitions.csv (%d rows): only mine %d, only csv %d" % (len(csv_ev), len(mine - csv_norm), len(csv_norm - mine)))

    # host / identity helpers
    def summarize(es, label):
        relays = {e["fp"] for e in es}
        hosts = {e["ip"] for e in es}
        ops = {oper(e["fp"], e["ch"]) for e in es}
        named = {contact[e["ch"]] for e in es if e["ch"] and contact.get(e["ch"])}
        nocon = [e for e in es if not (e["ch"] and contact.get(e["ch"]))]
        ases = Counter("%s %s" % asn(e["ip"]) for e in es)
        kinds = Counter(e["kind"] for e in es)
        dirs = Counter("%s->%s" % (e["old"], e["new"]) for e in es)
        famn = sum(e["fp"] in fam for e in es)
        p("  %s: %s -> %s | events %d, relays %d, hosts %d, operators %d (named contacts %d + no-contact relays %d on %d hosts), family events %d | kinds %s | %s | ASes %s"
          % (label, es[0]["pub"], es[-1]["pub"], len(es), len(relays), len(hosts), len(ops), len(named),
             len({e["fp"] for e in nocon}), len({e["ip"] for e in nocon}), famn, dict(kinds), dict(dirs), dict(ases)))
        return relays, hosts, ops

    # ------------------------------------------------------------------ waves (15-min chaining)
    p("\n=== WAVES (all attacker-class transitions, gap <= 900 s)")
    waves = []
    for e in ev:
        if waves and e["t"] - waves[-1][-1]["t"] <= 900:
            waves[-1].append(e)
        else:
            waves.append([e])
    for i, w in enumerate(waves, 1):
        summarize(w, "wave %d" % i)

    def window(a, b, pred=lambda e: True):
        ta, tb = ts_epoch(a), ts_epoch(b)
        return [e for e in ev if ta <= e["t"] <= tb and pred(e)]

    # ------------------------------------------------------------------ E2
    p("\n=== E2 2026-10-01 OUR_POLICY waves")
    w1 = window("2026-10-01 14:00:00", "2026-10-01 15:00:00")
    summarize(w1, "10-01 14:xx")
    for e in w1:
        p("    %s %s %s %s %s %s->%s %s" % (e["pub"], e["fp"], e["nick"], e["ip"], asn(e["ip"])[0], e["old"], e["new"], e["kind"]))
    w2 = window("2026-10-01 15:00:00", "2026-10-01 16:30:00")
    r2, h2, o2 = summarize(w2, "10-01 15:xx")
    p("    family relays in wave: %d; FranTech relays: %d; FranTech hosts: %d" % (
        len(r2 & fam), sum(asn(e["ip"])[0] == "53667" for e in w2), len({e["ip"] for e in w2 if asn(e["ip"])[0] == "53667"})))
    p("    first: %s %s %s %s; last: %s %s %s %s" % (w2[0]["pub"], w2[0]["fp"], w2[0]["nick"], w2[0]["ip"],
                                                  w2[-1]["pub"], w2[-1]["fp"], w2[-1]["nick"], w2[-1]["ip"]))
    for e in w2:
        if e["kind"] != "reload":
            p("    non-reload: %s %s %s %s %s" % (e["pub"], e["fp"], e["nick"], e["ip"], e["kind"]))
    pol16 = Counter(e["nick"].rstrip("0123456789") for e in w2)
    p("    nickname stems: %s" % dict(pol16.most_common(5)))
    # OUR_POLICY relays total by 10-02 09:27
    ourrel = {e["fp"] for e in ev if e["new"] == "OUR_POLICY" and e["t"] < ts_epoch("2026-10-02 09:27:42")}
    p("    relays that published OUR_POLICY before the first near-open: %d" % len(ourrel))

    # ------------------------------------------------------------------ E3
    p("\n=== E3 first near-open and the 2026-10-02 09:27:42 wave")
    w3 = window("2026-10-02 09:00:00", "2026-10-02 10:00:00")
    summarize(w3, "10-02 09:xx all")
    w3f = [e for e in w3 if e["fp"] in fam]
    w3n = [e for e in w3 if e["fp"] not in fam]
    summarize(w3f, "  family part")
    summarize(w3n, "  non-family part")
    p("    family part old classes: %s" % dict(Counter(e["old"] for e in w3f)))
    w3n_into = [e for e in w3n if e["new"] == "near-open"]
    summarize(w3n_into, "  non-family into near-open")
    p("    first near-open: %s %s %s %s" % (w3[0]["pub"], w3[0]["fp"], w3[0]["nick"], w3[0]["ip"]))
    p("    last event: %s %s %s %s %s->%s" % (w3[-1]["pub"], w3[-1]["fp"], w3[-1]["nick"], w3[-1]["ip"], w3[-1]["old"], w3[-1]["new"]))
    fam_v = vset & fam
    p("    family victims overall: %d relays / %d hosts" % (len(fam_v), len({descs[f][-1][3] for f in fam_v})))
    # family members by the original net_victims.py (nickname/contact LIKE quetzal) definition
    alt = {fp for (fp,) in db.execute("SELECT DISTINCT d.fp FROM descriptor d LEFT JOIN contact c ON c.contact_h=d.contact_h "
                                      "WHERE lower(d.nickname) LIKE '%quetzal%' OR lower(c.text) LIKE '%quetzal%'")} | seeds
    p("    family set size (task def) %d vs LIKE-quetzal def %d; victims: %d vs %d" % (len(fam), len(alt), len(fam & vset), len(alt & vset)))

    # ------------------------------------------------------------------ E4
    p("\n=== E4 later flips")
    for a, b in (("2026-10-02 10:00:00", "2026-10-02 23:59:59"), ("2026-10-03 00:00:00", "2026-10-03 23:59:59"),
                 ("2026-10-04 00:00:00", "2026-10-04 20:00:00")):
        w = window(a, b, lambda e: e["new"] != "other")
        if not w:
            continue
        summarize(w, "%s..%s (into/first/between)" % (a, b))
        for e in w:
            extra = ""
            if e["kind"] == "first":
                prior = db.execute("SELECT DISTINCT fp, nickname FROM descriptor WHERE address=? AND fp<>? AND pub_epoch < ?",
                                   [e["ip"], e["fp"], e["t"]]).fetchall()
                same_port = db.execute("SELECT DISTINCT fp, nickname FROM descriptor WHERE address=? AND or_port=? AND fp<>? AND pub_epoch < ?",
                                       [e["ip"], e["orp"], e["fp"], e["t"]]).fetchall()
                fpv = [x for x in prior if x[0] in vset]
                extra = " | prior fps at IP: %d (victims %s); same IP:ORPort: %s" % (
                    len(prior), [x[1] + " " + x[0] for x in fpv], [x[1] + " " + x[0] for x in same_port])
            p("    %s %s %-20s %-16s %s %s->%s %s%s" % (e["pub"], e["fp"], e["nick"], e["ip"], asn(e["ip"])[0],
                                                       e["old"], e["new"], e["kind"], extra))

    # ------------------------------------------------------------------ E5 votes
    p("\n=== E5 directory-authority actions")
    auths = sorted({a for (a,) in db.execute("SELECT DISTINCT auth FROM vote")})
    known = defaultdict(set)
    for a, kf in db.execute("SELECT auth, known_flags FROM vote"):
        known[a].add("BadExit" in kf.split())
    fa = {fp: epoch_ts(t) for fp, t in first_att.items()}
    preflag = set()
    for fp, start, flags in db.execute("SELECT fp, start_va, flags FROM cons_interval WHERE fp IN (SELECT fp FROM victim)"):
        if start < fa[fp] and ("BadExit" in flags.split() or "MiddleOnly" in flags.split()):
            preflag.add(fp)
    p("  victims carrying BadExit/MiddleOnly in a consensus before their first attacker descriptor: %s" % sorted(preflag))
    for a in auths:
        firsts, per_va = {}, defaultdict(Counter)
        for va, fp, flags in db.execute("SELECT va, fp, flags FROM vote_entry WHERE auth=? ORDER BY va", [a]):
            if fp not in vset or fp in preflag:
                continue
            fl = flags.split()
            for f in ("BadExit", "MiddleOnly"):
                if f in fl:
                    firsts.setdefault(f, (va, fp))
                    per_va[va][f] += 1
        nb = Counter({va: c["BadExit"] for va, c in per_va.items()})
        nm = Counter({va: c["MiddleOnly"] for va, c in per_va.items()})
        fb, fm = firsts.get("BadExit"), firsts.get("MiddleOnly")
        p("  NEW-FLAG %-10s knows BadExit %s | first BadExit %s (n=%s) | first MiddleOnly %s (n=%s) | max BadExit %s | max MiddleOnly %s"
          % (a, sorted(known[a]), fb, fb and nb[fb[0]], fm, fm and nm[fm[0]],
             nb.most_common(1)[0][::-1] if nb else None, nm.most_common(1)[0][::-1] if nm else None))
    vs_csv = {r["authority"]: r for r in csv.DictReader(open(os.path.join(ROOT, "net", "votes_authority_summary.csv")))}
    for a in auths:
        r = vs_csv.get(a, {})
        p("  CSV %-10s first BadExit %s max %s | first MiddleOnly %s max %s | first omission %s max %s" % (
            a, r.get("first_va_BadExit_on_victim"), r.get("max_victims_BadExit"), r.get("first_va_MiddleOnly_on_victim"),
            r.get("max_victims_MiddleOnly"), r.get("first_va_omitting_victims"), r.get("max_victims_omitted")))
    for a in auths:
        rows = db.execute("SELECT va, fp, flags, policy FROM vote_entry WHERE auth=? ORDER BY va", [a]).fetchall()
        res = {}
        for va, fp, flags, pol in rows:
            if fp not in vset:
                continue
            fl = flags.split()
            for f in ("BadExit", "MiddleOnly"):
                if f in fl:
                    k_any = f + "_any"
                    res.setdefault(k_any, (va, fp))
                    if va >= fa[fp]:
                        res.setdefault(f + "_after_attack", (va, fp))
                    if pol in ATT:
                        res.setdefault(f + "_attacker_pline", (va, fp))
        maxc = db.execute("""SELECT va, sum(instr(' '||flags||' ',' BadExit ')>0), sum(instr(' '||flags||' ',' MiddleOnly ')>0)
                             FROM vote_entry WHERE auth=? AND fp IN (SELECT fp FROM victim) GROUP BY va""", [a]).fetchall()
        mb = max(maxc, key=lambda x: (x[1], x[0]), default=None)
        mm = max(maxc, key=lambda x: (x[2], x[0]), default=None)
        p("  %-10s knows BadExit %s | first BadExit after attack %s | on attacker p %s | any %s | first MiddleOnly after attack %s | on attacker p %s | any %s | max BadExit %s | max MiddleOnly %s"
          % (a, sorted(known[a]), res.get("BadExit_after_attack"), res.get("BadExit_attacker_pline"), res.get("BadExit_any"),
             res.get("MiddleOnly_after_attack"), res.get("MiddleOnly_attacker_pline"), res.get("MiddleOnly_any"),
             mb and (mb[1], mb[0]), mm and (mm[2], mm[0])))
    # consensus side
    vas = [va for (va,) in db.execute("SELECT DISTINCT va FROM cons_entry ORDER BY va")]
    p("  cons_entry valid-afters: %d (%s .. %s)" % (len(vas), vas[0], vas[-1]))
    per = {}
    for va, fp, flags, pol in db.execute("SELECT va, fp, flags, policy FROM cons_entry WHERE va >= '2026-10-01' ORDER BY va"):
        d = per.setdefault(va, Counter())
        fl = flags.split()
        d["n"] += 1
        d["BadExit"] += "BadExit" in fl
        d["MiddleOnly"] += "MiddleOnly" in fl
        att = pol in ATT
        d["att_p"] += att
        if att:
            d["att_p_" + ATT[pol]] += 1
        if fp in vset:
            d["v"] += 1
            d["v_att_p"] += att
            d["v_BadExit"] += "BadExit" in fl
            d["v_MiddleOnly"] += "MiddleOnly" in fl
            d["v_BadExit_after"] += ("BadExit" in fl) and va >= fa[fp]
            d["v_new_BadExit"] += ("BadExit" in fl) and fp not in preflag
            d["v_new_MO"] += ("MiddleOnly" in fl) and fp not in preflag
            d["v_MO_after"] += ("MiddleOnly" in fl) and va >= fa[fp]
            if att:
                d["v_att_neither"] += ("BadExit" not in fl and "MiddleOnly" not in fl)
                d["v_att_neither_noexit"] += ("BadExit" not in fl and "MiddleOnly" not in fl and "Exit" not in fl)
                d["v_att_neither_exit"] += ("BadExit" not in fl and "MiddleOnly" not in fl and "Exit" in fl)
                d["v_att_fam"] += fp in fam
                d["v_att_neither_fam"] += (fp in fam and "BadExit" not in fl and "MiddleOnly" not in fl)
    first_be = next((va for va in sorted(per) if per[va]["v_BadExit_after"] > 0), None)
    first_mo = next((va for va in sorted(per) if per[va]["v_MO_after"] > 0), None)
    p("  first consensus with BadExit on a victim after its first attacker descriptor: %s (%d); MiddleOnly: %s (%d)"
      % (first_be, per[first_be]["v_BadExit_after"], first_mo, per[first_mo]["v_MO_after"]))
    if first_be:
        lst = db.execute("SELECT fp, nickname, flags FROM cons_entry WHERE va=? AND instr(flags,'BadExit')>0 AND fp IN (SELECT fp FROM victim)", [first_be]).fetchall()
        p("    victims with BadExit at %s: %d (incl. pre-flagged)" % (first_be, len(lst)))
    first_nbe = next((va for va in sorted(per) if per[va]["v_new_BadExit"] > 0), None)
    first_nmo = next((va for va in sorted(per) if per[va]["v_new_MO"] > 0), None)
    p("  first consensus with BadExit on a victim not pre-flagged: %s (%d; MiddleOnly there %d); first MiddleOnly: %s (%d)"
      % (first_nbe, per[first_nbe]["v_new_BadExit"], per[first_nbe]["v_new_MO"], first_nmo, per[first_nmo]["v_new_MO"]))
    def flagged(va):
        return {fp: flags.split() for fp, flags in db.execute("SELECT fp, flags FROM cons_entry WHERE va=? AND fp IN (SELECT fp FROM victim)", [va])}
    f11, f12 = flagged("2026-10-05 11:00:00"), flagged("2026-10-05 12:00:00")
    lost = [fp for fp in f12 if fp in f11 and ({"BadExit", "MiddleOnly"} & set(f11[fp])) and not ({"BadExit", "MiddleOnly"} & set(f12[fp]))]
    p("  victims flagged BadExit/MiddleOnly at 10-05 11:00 and listed at 12:00 with neither: %d (family %d)" % (len(lost), sum(fp in fam for fp in lost)))
    peak_be = max(per, key=lambda va: (per[va]["BadExit"], va))
    peak_mo = max(per, key=lambda va: (per[va]["MiddleOnly"], va))
    p("  peak BadExit per consensus (Oct): %d at %s (MiddleOnly there %d); peak MiddleOnly %d at %s"
      % (per[peak_be]["BadExit"], peak_be, per[peak_be]["MiddleOnly"], per[peak_mo]["MiddleOnly"], peak_mo))
    peak_vbe = max(per, key=lambda va: (per[va]["v_BadExit"], va))
    p("  peak victims with BadExit: %d at %s (victims MiddleOnly %d)" % (per[peak_vbe]["v_BadExit"], peak_vbe, per[peak_vbe]["v_MiddleOnly"]))
    for va in ("2026-09-30 23:00:00", "2026-10-01 14:00:00", "2026-10-04 17:00:00", "2026-10-04 18:00:00", "2026-10-04 19:00:00",
               "2026-10-04 20:00:00", "2026-10-04 21:00:00", "2026-10-05 08:00:00", "2026-10-05 09:00:00",
               "2026-10-05 10:00:00", "2026-10-05 11:00:00", "2026-10-05 12:00:00", "2026-10-05 13:00:00",
               "2026-10-05 14:00:00", "2026-10-05 15:00:00", "2026-10-05 16:00:00", "2026-10-05 17:00:00",
               "2026-10-06 00:00:00", "2026-10-07 02:00:00"):
        if va in per:
            p("    %s %s" % (va, dict(per[va])))
    last_att = max((va for va in per if per[va]["att_p"] > 0), default=None)
    p("  LAST consensus (cons_entry) with any near-open/OUR_POLICY p line: %s (%s)" % (last_att, dict(per[last_att])))
    rows = db.execute("SELECT fp, nickname, ip, flags, policy FROM cons_entry WHERE va=? AND policy IN (?,?)",
                      [last_att, NEAR_OPEN, OUR_POLICY]).fetchall()
    for r in rows:
        p("    %s %s %s %s [%s] %s" % (r[0], r[1], r[2], asn(r[2])[0], r[3], ATT[r[4]]))
    nxt = [va for va in vas if va > last_att]
    p("  next consensus after it: %s" % (nxt[0] if nxt else None))
    # consensus.counts (whole window, all consensuses)
    lastc = {}
    for va, counts in db.execute("SELECT va, counts FROM consensus ORDER BY va"):
        c = ast.literal_eval(counts)
        for k in ("pol:near-open", "pol:OUR_POLICY"):
            if c.get(k, 0) > 0:
                lastc.setdefault("first_" + k, va)
                lastc["last_" + k] = va
    p("  consensus.counts: %s" % lastc)

    # ------------------------------------------------------------------ E6 rollback
    p("\n=== E6 rollback 2026-10-04 22:21:18 .. 22:47:33")
    w6 = window("2026-10-04 22:00:00", "2026-10-04 23:30:00")
    summarize(w6, "10-04 22:xx")
    ident = 0
    for e in w6:
        rows = descs[e["fp"]]
        hs = []
        for r in rows:
            if r[1] > e["t"]:
                break
            if not hs or hs[-1] != r[6]:
                hs.append(r[6])
        # hs[-1] = new policy; hs[-2] = attacker policy replaced; hs[-3] = policy before that change
        same = len(hs) >= 3 and hs[-1] == hs[-3]
        same_any_pre = any(h == hs[-1] for h in hs[:-1] if pol_cls.get(h) == "other")
        ident += same
        p("    %s %s %-18s %-16s %s %s->%s %s byte-identical-to-before-previous-change=%s any-earlier=%s" % (
            e["pub"], e["fp"], e["nick"], e["ip"], asn(e["ip"])[0], e["old"], e["new"], e["kind"], same, same_any_pre))
    p("    identical: %d of %d events" % (ident, len(w6)))
    rb = [r for r in csv.DictReader(open(os.path.join(ROOT, "net", "rollback_check.csv")))
          if "2026-10-04 22:21:18" <= r["published"] <= "2026-10-04 22:47:33"]
    p("  rollback_check.csv rows in window: %d; kinds %s; identical col %s; transitions %s" % (
        len(rb), dict(Counter(r["kind"] for r in rb)), dict(Counter(r["identical_to_policy_before_previous_change"] for r in rb)),
        dict(Counter(r["old_class"] + "->" + r["new_class"] for r in rb))))

    # ------------------------------------------------------------------ E7 family sweep
    p("\n=== E7 family restart sweep 2026-10-05")
    ta, tb = ts_epoch("2026-10-05 08:00:00"), ts_epoch("2026-10-05 12:00:00")
    boots = []
    for fp in fam:
        rows = db.execute("SELECT published, pub_epoch, address, boot_epoch FROM descriptor WHERE fp=? ORDER BY pub_epoch", [fp]).fetchall()
        last_boot, prev = None, None
        for pub, pe, addr, boot in rows:
            if prev is not None and boot is not None:
                if last_boot is not None and abs(boot - last_boot) > 2 and boot >= prev and ta <= boot <= tb:
                    boots.append((boot, fp, addr))
                last_boot = boot
            elif prev is None:
                last_boot = boot
            prev = pe
    boots.sort()
    if boots:
        p("  family restarts 08:00-12:00 on 10-05: %d relays, %d hosts, first %s %s %s, last %s %s %s" % (
            len({b[1] for b in boots}), len({b[2] for b in boots}), epoch_ts(boots[0][0]), boots[0][1], boots[0][2],
            epoch_ts(boots[-1][0]), boots[-1][1], boots[-1][2]))
        hosts_first = {}
        for b in boots:
            hosts_first.setdefault(b[2], b[0])
        p("  hosts: %d; host first restarts span %s .. %s; relays restarted %d" % (
            len(hosts_first), epoch_ts(min(hosts_first.values())), epoch_ts(max(hosts_first.values())), len({b[1] for b in boots})))
    sw = list(csv.DictReader(open(os.path.join(ROOT, "out", "repro_sweep_20261005.csv"))))
    p("  repro_sweep_20261005.csv: %d hosts, %d relays, %s .. %s; ASes %s" % (
        len(sw), sum(int(r["relays_restarted_on_host"]) for r in sw), min(r["first_restart_utc"] for r in sw),
        max(r["first_restart_utc"] for r in sw), dict(Counter(r["as_name"] for r in sw))))

    # ------------------------------------------------------------------ E8 end state
    p("\n=== E8 end of window")
    lv = vas[-1]
    last_desc = db.execute("SELECT max(published) FROM descriptor").fetchone()[0]
    p("  last consensus %s, last descriptor %s" % (lv, last_desc))
    inv = db.execute("SELECT fp, nickname, ip, flags, policy FROM cons_entry WHERE va=? AND fp IN (SELECT fp FROM victim)", [lv]).fetchall()
    for r in inv:
        p("    victim in final consensus: %s %s %s %s [%s] p=%s" % (r[0], r[1], r[2], asn(r[2])[0], r[3], r[4]))
    natt = db.execute("SELECT count(*) FROM cons_entry WHERE va=? AND policy IN (?,?)", [lv, NEAR_OPEN, OUR_POLICY]).fetchone()[0]
    p("  final consensus: victims listed %d; relays with attacker p line %d; total relays %d" % (
        len(inv), natt, db.execute("SELECT count(*) FROM cons_entry WHERE va=?", [lv]).fetchone()[0]))
    cut = ts_epoch(last_desc) - 86400
    still = []
    for fp in vict:
        r = descs[fp][-1]
        if pol_cls.get(r[6]) != "other" and r[1] >= cut:
            still.append((fp, r[2], r[3], r[0], pol_cls[r[6]]))
    p("  victims whose last descriptor is attacker-class and published >= %s: %d (family %d) by class %s; FranTech %d; ASes %s"
      % (epoch_ts(cut), len(still), sum(s[0] in fam for s in still), dict(Counter(s[4] for s in still)),
         sum(asn(s[2])[0] == "53667" for s in still), dict(Counter(asn(s[2])[0] for s in still))))
    p("    operators among them: %d" % len({oper(s[0], descs[s[0]][-1][5]) for s in still}))
    lastatt = sum(pol_cls.get(descs[fp][-1][6]) != "other" for fp in vict)
    p("  victims whose last descriptor is attacker-class (any time): %d" % lastatt)
    in_last_any = {fp for (fp,) in db.execute("SELECT fp FROM cons_entry WHERE va=?", [lv])}
    p("  of the %d still-publishing, in final consensus: %d" % (len(still), len({s[0] for s in still} & in_last_any)))
    pub_last24 = {fp for (fp,) in db.execute("SELECT DISTINCT fp FROM descriptor WHERE pub_epoch >= ?", [cut])}
    p("  victims publishing any descriptor in last 24 h: %d" % len(vset & pub_last24))
    lastvote = db.execute("SELECT max(va) FROM vote").fetchone()[0]
    nauth = db.execute("SELECT count(*) FROM vote WHERE va=?", [lastvote]).fetchone()[0]
    listed = Counter()
    for (fp,) in db.execute("SELECT fp FROM vote_entry WHERE va=?", [lastvote]):
        listed[fp] += 1
    absent = Counter(fp for (fp,) in db.execute("SELECT fp FROM vote_absent WHERE va=?", [lastvote]))
    st = [s[0] for s in still]
    p("  last vote round %s (%d authorities): of the %d still publishing, listed by >=1 authority: %d; by how many: %s; in vote_absent: %d (per-relay counts %s)"
      % (lastvote, nauth, len(st), sum(listed[f] > 0 for f in st), dict(Counter(listed[f] for f in st)),
         sum(absent[f] > 0 for f in st), dict(Counter(absent[f] for f in st))))
    for s_ in still:
        p("    still: %s %-18s %-16s %s last=%s %s listed_by=%d" % (s_[0], s_[1], s_[2], asn(s_[2])[0], s_[3], s_[4], listed[s_[0]]))
    # ever flagged in a consensus / in any vote, after first attacker descriptor (pre-flagged excluded)
    cons_fl, vote_fl, omitted = set(), set(), set()
    for fp, va, flags in db.execute("SELECT fp, start_va, flags FROM cons_interval WHERE fp IN (SELECT fp FROM victim)"):
        pass
    for fp, flags, va in db.execute("SELECT fp, flags, va FROM cons_entry WHERE fp IN (SELECT fp FROM victim)"):
        if va >= fa[fp] and ({"BadExit", "MiddleOnly"} & set(flags.split())):
            cons_fl.add(fp)
    for fp, flags, va in db.execute("SELECT fp, flags, va FROM vote_entry WHERE fp IN (SELECT fp FROM victim)"):
        if va >= fa[fp] and ({"BadExit", "MiddleOnly"} & set(flags.split())):
            vote_fl.add(fp)
    for fp, va in db.execute("SELECT fp, va FROM vote_absent WHERE fp IN (SELECT fp FROM victim)"):
        if va >= fa[fp]:
            omitted.add(fp)
    p("  victims ever BadExit/MiddleOnly in a consensus after first attacker desc: %d (excl. pre-flagged %d); in >=1 vote: %d; omitted by >=1 authority after first attacker desc: %d; flagged-in-vote or omitted: %d of %d"
      % (len(cons_fl), len(cons_fl - preflag), len(vote_fl), len(omitted), len(vote_fl | omitted), len(vset)))
    never_cons = vset - cons_fl
    p("    never flagged in consensus: %d (family %d); of them in no consensus after first attacker desc: %d" % (
        len(never_cons), len(never_cons & fam),
        sum(1 for f in never_cons if not db.execute("SELECT 1 FROM cons_entry WHERE fp=? AND va>=? LIMIT 1", [f, fa[f]]).fetchone())))

    # ------------------------------------------------------------------ X exposure
    p("\n=== X exit-weight exposure")
    rows = list(csv.DictReader(open(os.path.join(ROOT, "net", "exit_weight_exposure.csv"))))
    pk = max(rows, key=lambda r: float(r["pct_usable_exit_weight_victims"]))
    pn = max(rows, key=lambda r: (int(r["n_victims_attacker_usable_exit"]), r["valid_after"]))
    p("  CSV peak pct %s at %s (n=%s, bw %s / %s); peak n %s at %s (pct %s)" % (
        pk["pct_usable_exit_weight_victims"], pk["valid_after"], pk["n_victims_attacker_usable_exit"],
        pk["bw_victims_attacker_usable_exit"], pk["bw_exit_usable"], pn["n_victims_attacker_usable_exit"],
        pn["valid_after"], pn["pct_usable_exit_weight_victims"]))
    best = None
    for va in vas:
        tot_u = vic_u = n_u = 0
        for fp, flags, bw, pol in db.execute("SELECT fp, flags, bw, policy FROM cons_entry WHERE va=?", [va]):
            fl = flags.split()
            if "Exit" in fl and "BadExit" not in fl:
                tot_u += bw or 0
                if pol in ATT:
                    vic_u += bw or 0
                    n_u += 1
        pct = 100.0 * vic_u / tot_u if tot_u else 0
        if best is None or pct > best[0]:
            best = (pct, va, n_u, vic_u, tot_u)
    p("  recomputed from cons_entry (attacker p line, Exit, no BadExit): peak %.4f %% at %s, %d relays, bw %d / %d" % best)


if __name__ == "__main__":
    main()
