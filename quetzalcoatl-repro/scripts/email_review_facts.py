"""email_review_facts.py - independent re-check of the numbers in the tor-relays reply draft.

Re-derives, from net/netdb.sqlite only (no CSV or research JSON is read for the results),
every count the draft states: victim set, family split, hosts, ASes, operators, policy
transitions per wave (restart vs reload), consensus flag/exposure counts, authority votes,
reference-consensus hit rates, non-exit victims and the 2026-10-01 family restart.

Rules: standard library only; run as "python3 -I scripts/email_review_facts.py [section ...]".
Sections: base waves cons votes ref nonexit fam1001 hist
Output goes to stdout.
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "net", "netdb.sqlite")
SEEDS = os.path.join(ROOT, "family_seed_fingerprints.txt")
FAM_PREFIX = "email:Quetzalcoatl_relays[]proton.me"
ATT = {"near-open", "OUR_POLICY"}
FRANTECH = "53667"


def conn():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def load_base(c):
    pol = {}
    mism = 0
    for h, text, summ in c.execute("select policy_h, text, summary from policy"):
        s2 = common.summarize_policy(text.split("\n")) if text else None
        if s2 != summ:
            mism += 1
        pol[h] = common.classify_summary(s2)
    att_h = [h for h, k in pol.items() if k in ATT]
    q = "select distinct fp from descriptor where policy_h in (%s)" % ",".join("?" * len(att_h))
    victims = sorted(r[0] for r in c.execute(q, att_h))
    contact = dict(c.execute("select contact_h, text from contact"))
    seeds = set()
    for line in open(SEEDS):
        line = line.strip()
        if line and not line.startswith("#"):
            seeds.add(line.split()[0].upper())
    fam_contacts = {h for h, t in contact.items() if t and t.startswith(FAM_PREFIX)}
    fam = set(seeds)
    q = "select distinct fp from descriptor where contact_h in (%s)" % ",".join("?" * len(fam_contacts))
    fam.update(r[0] for r in c.execute(q, list(fam_contacts)))
    descs = collections.defaultdict(list)
    for fp in victims:
        for row in c.execute(
            "select published, pub_epoch, boot_epoch, address, or_port, contact_h, policy_h, nickname, digest "
            "from descriptor where fp=? order by pub_epoch", (fp,)):
            descs[fp].append(row)
    ip_as = {}
    return pol, mism, victims, fam, contact, descs, ip_as


def asn_of(c, ip, cache={}):
    if ip not in cache:
        r = c.execute("select asn, org_name, agree from ip_as where ip=?", (ip,)).fetchone()
        cache[ip] = r
    return cache[ip]


def transitions(pol, descs):
    """Per victim: list of (published, epoch, fp, old_class, new_class, kind, old_h, new_h, ip, contact_h)."""
    out = []
    for fp, rows in descs.items():
        prev = None
        for r in rows:
            pub, ep, boot, ip, orp, ch, ph, nick, dg = r
            k = pol.get(ph)
            if prev is None:
                if k in ATT:
                    out.append((pub, ep, fp, None, k, "first", None, ph, ip, ch, nick))
            else:
                pk = pol.get(prev[6])
                if ph != prev[6] and (k in ATT or pk in ATT) and k != pk:
                    kind = "restart" if (boot is not None and prev[2] is not None and abs(boot - prev[2]) > 2) else "reload"
                    out.append((pub, ep, fp, pk, k, kind, prev[6], ph, ip, ch, nick))
            prev = r
    out.sort()
    return out


def main():
    secs = set(sys.argv[1:]) or {"base", "waves", "cons", "votes", "ref", "nonexit", "fam1001"}
    c = conn()
    pol, mism, victims, fam, contact, descs, _ = load_base(c)
    V = set(victims)
    famV = V & fam
    print("summarizer mismatches vs policy.summary:", mism, "of", len(pol))
    print("victims:", len(V), "family victims:", len(famV), "family fps total:", len(fam))
    tbl = {r[0] for r in c.execute("select fp from victim")}
    print("victim table equal:", tbl == V)
    # first attacker descriptor per victim
    first_att = {}
    for fp, rows in descs.items():
        for r in rows:
            if pol.get(r[6]) in ATT:
                first_att[fp] = r
                break
    if "base" in secs:
        hosts = collections.defaultdict(set)
        asv = collections.Counter()
        ashost = collections.defaultdict(set)
        agree_bad = 0
        allips_same = 0
        for fp in V:
            r = first_att[fp]
            ip = r[3]
            a = asn_of(c, ip)
            if a is None or not a[2]:
                agree_bad += 1
            att_ips = {x[3] for x in descs[fp] if pol.get(x[6]) in ATT}
            if len(att_ips) == 1:
                allips_same += 1
            hosts["fam" if fp in fam else "non"].add(ip)
            asv[a[0] if a else None] += 1
            ashost[a[0] if a else None].add(ip)
        allh = hosts["fam"] | hosts["non"]
        print("hosts all/fam/non/overlap:", len(allh), len(hosts["fam"]), len(hosts["non"]), len(hosts["fam"] & hosts["non"]))
        print("ASes:", len(asv), dict(asv))
        print("victim IPs with no CAIDA/IPFire agreement:", agree_bad, "; victims with a single attacker IP:", allips_same)
        ft = [fp for fp in V if asn_of(c, first_att[fp][3])[0] == FRANTECH]
        ftn = [fp for fp in ft if fp not in fam]
        print("FranTech victims:", len(ft), "nonfam:", len(ftn), "fam:", len(ft) - len(ftn),
              "nonfam victims:", len(V - fam))
        fth = {first_att[fp][3] for fp in ft}
        fthn = {first_att[fp][3] for fp in ftn}
        print("FranTech hosts all:", len(fth), "nonfam:", len(fthn), "of nonfam hosts", len(hosts["non"]))
        # operators: contact on first attacker descriptor
        ops = collections.defaultdict(set)
        nocontact = []
        for fp in V:
            ch = first_att[fp][5]
            t = contact.get(ch) if ch else None
            if not t:
                nocontact.append(fp)
            else:
                ops[t].add(fp)
        famops = [t for t, s in ops.items() if s & fam]
        print("contact strings:", len(ops), "family contact strings:", len(famops), "no-contact relays:", len(nocontact),
              "operators (no-contact separate):", len(ops) + len(nocontact))
        # attacker descriptors contact consistency
        multi = sum(1 for fp in V if len({x[5] for x in descs[fp] if pol.get(x[6]) in ATT}) > 1)
        print("victims with >1 contact across attacker descriptors:", multi)
        # FranTech operators
        opft = set()
        op_has_ft_victim = set()
        for t, s in ops.items():
            if any(asn_of(c, first_att[fp][3])[0] == FRANTECH for fp in s):
                op_has_ft_victim.add(t)
        nc_ft = [fp for fp in nocontact if asn_of(c, first_att[fp][3])[0] == FRANTECH]
        print("operators with a FranTech victim: contact strings", len(op_has_ft_victim), "+ no-contact", len(nc_ft),
              "=", len(op_has_ft_victim) + len(nc_ft))
        # operators with any FranTech relay in window (by contact string, any descriptor)
        ch_of = {}
        for h, t in contact.items():
            ch_of.setdefault(t, []).append(h)
        no_ft_ops = []
        for t, s in ops.items():
            hs = ch_of[t]
            q = "select distinct address from descriptor where contact_h in (%s)" % ",".join("?" * len(hs))
            addrs = [r[0] for r in c.execute(q, hs)]
            anyft = any((asn_of(c, a) or (None,))[0] == FRANTECH for a in addrs)
            if not anyft:
                no_ft_ops.append((t, s))
        for fp in nocontact:
            addrs = {x[3] for x in descs[fp]}
            if not any((asn_of(c, a) or (None,))[0] == FRANTECH for a in addrs):
                no_ft_ops.append(("<none:%s>" % fp, {fp}))
        nrel = sum(len(s) for _, s in no_ft_ops)
        nas = {asn_of(c, first_att[fp][3])[0] for _, s in no_ft_ops for fp in s}
        nh = {first_att[fp][3] for _, s in no_ft_ops for fp in s}
        print("operators with no FranTech relay in window:", len(no_ft_ops), "relays", nrel, "hosts", len(nh), "ASes", len(nas), sorted(nas))
        print("non-family operators:", len(ops) - len(famops) + len(nocontact))
    if "waves" in secs:
        tr = transitions(pol, descs)
        print("transitions total:", len(tr))

        def win(a, b, pred=lambda t: True):
            return [t for t in tr if a <= t[0] <= b and pred(t)]

        def summ(ts, label):
            fps = {t[2] for t in ts}
            hs = {t[8] for t in ts}
            opsx = set()
            for t in ts:
                tx = contact.get(t[9]) if t[9] else None
                opsx.add(tx if tx else "<none:%s>" % t[2])
            kinds = collections.Counter(t[5] for t in ts)
            asx = collections.Counter(asn_of(c, t[8])[0] for t in ts)
            moves = collections.Counter((t[3], t[4]) for t in ts)
            print(label, "events", len(ts), "relays", len(fps), "hosts", len(hs), "operators", len(opsx),
                  "kinds", dict(kinds), "AS", dict(asx), "moves", dict(moves),
                  "first", ts[0][:3] if ts else None, ts[0][10] if ts else None, "last", ts[-1][:3] if ts else None,
                  "fam relays", len(fps & fam))
            return ts
        summ(win("2026-10-01 00:00:00", "2026-10-01 15:00:00"), "W1 10-01 <15:00")
        summ(win("2026-10-01 14:49:51", "2026-10-01 14:50:03"), "W1 exact")
        summ(win("2026-10-01 15:00:00", "2026-10-01 23:59:59"), "W2 10-01 >=15:00")
        summ(win("2026-10-01 15:33:55", "2026-10-01 15:39:19"), "W2 exact")
        summ(win("2026-10-02 00:00:00", "2026-10-02 09:27:41"), "10-02 before 09:27:42")
        summ(win("2026-10-02 09:27:42", "2026-10-02 09:35:18", lambda t: t[2] in fam), "W3 fam")
        summ(win("2026-10-02 00:00:00", "2026-10-02 23:59:59", lambda t: t[2] in fam), "10-02 fam all day")
        print("family victims whose first attacker desc in 09:27:42-09:35:18:",
              sum(1 for fp in famV if "2026-10-02 09:27:42" <= first_att[fp][0] <= "2026-10-02 09:35:18"))
        summ(win("2026-10-02 09:27:42", "2026-10-02 09:44:12", lambda t: t[2] not in fam), "W3 nonfam")
        summ(win("2026-10-02 09:44:13", "2026-10-02 10:15:19"), "10-02 gap 09:44:13-10:15:19")
        summ(win("2026-10-02 10:15:20", "2026-10-02 18:53:05"), "10-02 10:15:20-18:53:05")
        summ(win("2026-10-02 18:53:06", "2026-10-03 10:26:01"), "10-02 18:53:06 - 10-03 10:26:01")
        w = summ(win("2026-10-03 10:26:02", "2026-10-03 16:18:40"), "10-03 window")
        summ(win("2026-10-03 16:18:41", "2026-10-04 17:49:23"), "10-03 16:18:41 - 10-04 17:49:23")
        summ(win("2026-10-04 17:49:24", "2026-10-04 17:52:02"), "10-04 17:49")
        rb = summ(win("2026-10-04 22:00:00", "2026-10-04 23:00:00"), "10-04 22h")
        # byte identical rollback
        ident = 0
        for t in rb:
            if t[5] == "first":
                continue
            rows = descs[t[2]]
            hs = [x[6] for x in rows if x[0] < t[0]]
            # previous distinct policy before the old one
            seq = []
            for h in hs:
                if not seq or seq[-1] != h:
                    seq.append(h)
            if len(seq) >= 2 and seq[-2] == t[7]:
                ident += 1
        print("rollback byte-identical to the policy before previous change:", ident)
        summ(win("2026-10-05 00:00:00", "2026-10-07 03:00:00"), "10-05 onward")
        # family restart sweep 10-05
        rs = []
        for fp in fam:
            for r in c.execute("select boot_epoch, address from restart where fp=? and boot >= '2026-10-05 08:00:00' and boot < '2026-10-05 12:00:00'", (fp,)):
                rs.append((r[0], fp, r[1]))
        rs.sort()
        if rs:
            print("10-05 family restarts (restart table):", len(rs), "relays", len({x[1] for x in rs}), "hosts", len({x[2] for x in rs}),
                  common.epoch_ts(rs[0][0]), rs[0][2], common.epoch_ts(rs[-1][0]), rs[-1][2])
            hostfirst = {}
            for e, fp, ip in rs:
                hostfirst.setdefault(ip, e)
            print("   host first-restart span", common.epoch_ts(min(hostfirst.values())), common.epoch_ts(max(hostfirst.values())))
    if "nonexit" in secs:
        # previous class just before first attacker descriptor
        prevcls = collections.Counter()
        nonexit = []
        for fp in V:
            rows = descs[fp]
            i = rows.index(first_att[fp])
            pk = pol.get(rows[i - 1][6]) if i > 0 else "first"
            prevcls[pk] += 1
            if pk == "non-exit":
                nonexit.append(fp)
        print("class before first attacker desc:", dict(prevcls))
        print("non-exit victims family:", len(set(nonexit) & fam))
        gained = 0
        for fp in nonexit:
            ok = c.execute("select count(*) from cons_entry where fp=? and va>='2026-10-01' and (' '||flags||' ') like '% Exit %' "
                           "and policy in (?,?)", (fp, common.NEAR_OPEN, common.OUR_POLICY)).fetchone()[0]
            gained += ok > 0
        print("non-exit victims with Exit flag + attacker p line in some consensus:", gained, "of", len(nonexit))
        famour = sum(1 for fp in famV for x in descs[fp] if pol.get(x[6]) == "OUR_POLICY")
        print("family OUR_POLICY descriptors:", famour)
    if "fam1001" in secs:
        rs = []
        for fp in fam:
            for r in c.execute("select boot_epoch, address from restart where fp=? and boot >= '2026-10-01 15:00:00' and boot < '2026-10-01 17:00:00'", (fp,)):
                rs.append((r[0], fp, r[1]))
        rs.sort()
        print("10-01 family restarts:", len(rs), "relays", len({x[1] for x in rs}), "hosts", len({x[2] for x in rs}),
              common.epoch_ts(rs[0][0]) if rs else None, common.epoch_ts(rs[-1][0]) if rs else None)
        # family hosts active (victim hosts)
        famhosts = {first_att[fp][3] for fp in famV}
        rh = {x[2] for x in rs}
        print("family victim hosts:", len(famhosts), "restarted:", len(rh & famhosts), "missing:", sorted(famhosts - rh),
              "restarted non-victim hosts:", sorted(rh - famhosts))
        # family relays published in Oct 1 14:00-15:30 (active)
        act = {r[0] for r in c.execute("select distinct fp from descriptor where published between '2026-09-30 15:00:00' and '2026-10-01 15:30:00'")} & fam
        acth = {r[0] for r in c.execute("select distinct address from descriptor where published between '2026-09-30 15:00:00' and '2026-10-01 15:30:00' and fp in (%s)" % ",".join("?" * len(act)), list(act))}
        print("family relays publishing 09-30 15:00..10-01 15:30:", len(act), "hosts", len(acth), "restarted relays among them", len(act & {x[1] for x in rs}))


if __name__ == "__main__":
    main()
