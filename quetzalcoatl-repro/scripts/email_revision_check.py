"""email_revision_check.py - re-checks the facts disputed by the reviewers of the tor-relays draft.

Reads net/netdb.sqlite (read-only) and net/victims.csv (victim list, family flag, first
attacker descriptor time). Prints, per section:
  fam1001   family hosts/relays restarted 2026-10-01 15:36:30-15:47:53 vs active family hosts
  revert    10-02 09:29:25-09:44:12 non-family OUR_POLICY -> other: equal to pre-10-01 hash?
  flags     victims ever BadExit/MiddleOnly in a consensus after first attacker descriptor;
            never-flagged victims still listed with an attacker p line after 10-04 21:00;
            victims never flagged in any vote
  usable    usable attacker exits (attacker p line, Exit, no BadExit) per consensus 10-04 20:00..
            10-05 17:00, and which relays stayed usable after 10-04 21:00
  authfirst first vote per authority flagging a victim (excluding pre-flagged 9CDB4020)
  nocontact victims without a contact line and their hosts
  rollback  10-04 22:21:18-22:47:33 policy moves
Standard library only; run as "python3 -I scripts/email_revision_check.py [section ...]".
"""
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "net", "netdb.sqlite")
VICT = os.path.join(ROOT, "net", "victims.csv")
NEAR = "reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999"
OURP = "reject 25,110,135,137-139,143,445,465,587,993,995,3389"
ATT_P = {NEAR, OURP}
PRE = "9CDB4020E69D9E7201C3D1A8BF9DE1DEBF997A76"


def conn():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def victims():
    with open(VICT, newline="") as f:
        return {r["fp"]: r for r in csv.DictReader(f)}


def hour_floor(ts):
    return ts[:14] + "00:00"


def ep(c, ts):
    return c.execute("select cast(strftime('%s', ?) as integer)", (ts,)).fetchone()[0]


def fam1001(c, V):
    fam = [fp for fp, r in V.items() if r["family"] == "1"]
    lo, hi = ep(c, "2026-10-01 15:36:30") - 2, ep(c, "2026-10-01 15:47:53") + 2
    hosts_all, hosts_r, rel_r = set(), set(), set()
    for fp in fam:
        hosts_all.add(V[fp]["ip"])
        n = c.execute("select count(*) from descriptor where fp=? and boot_epoch between ? and ?",
                      (fp, lo, hi)).fetchone()[0]
        if n:
            rel_r.add(fp)
            hosts_r.add(V[fp]["ip"])
    print("fam1001: family victims", len(fam), "hosts", len(hosts_all),
          "| restarted relays", len(rel_r), "hosts", len(hosts_r))
    print("  hosts not restarted:", sorted(hosts_all - hosts_r))
    print("  relays not restarted:", sorted(set(fam) - rel_r))
    sw = c.execute("select fp, min(boot_epoch), datetime(min(boot_epoch),'unixepoch') from descriptor "
                   "where fp in ('29FEFE36A5F66A6C93D24775B9D2364A3831B597',"
                   "'8427937D5A39E15699C850F26FED3CD59C379C48') and boot_epoch between ? and ? "
                   "group by fp", (lo, hi)).fetchall()
    print("  Switzerland2 boots:", sw)


def policy_class(c):
    return {h: (s, k) for h, s, k in c.execute("select policy_h, summary, class from policy")}


def revert(c, V):
    rows = c.execute("select fp, published, old_h, new_h, old_class, new_class from policy_event "
                     "where published between '2026-10-02 09:29:25' and '2026-10-02 09:44:12' "
                     "and old_class='OUR_POLICY' and new_class not in ('near-open','OUR_POLICY') "
                     "order by published").fetchall()
    same = 0
    for fp, pub, oh, nh, oc, nc in rows:
        pre = c.execute("select policy_h from descriptor where fp=? and published < '2026-10-01 15:30:00' "
                        "order by published desc limit 1", (fp,)).fetchone()
        eq = pre is not None and pre[0] == nh
        same += eq
        print("  ", fp, V.get(fp, {}).get("nickname"), pub, oc, "->", nc, "pre-10-01 equal:", eq)
    print("revert: rows", len(rows), "equal to pre-10-01 hash", same)


def flags(c, V):
    flagged, never = set(), set()
    for fp, r in V.items():
        start = hour_floor(r["first_attacker_desc"])
        n = c.execute("select count(*) from cons_entry where fp=? and va>=? and "
                      "(flags like '%BadExit%' or flags like '%MiddleOnly%')", (fp, start)).fetchone()[0]
        (flagged if n else never).add(fp)
    fam_never = sum(1 for fp in never if V[fp]["family"] == "1")
    print("flags: consensus-flagged", len(flagged), "never", len(never), "(family", fam_never, ")",
          "flagged excl 9CDB4020", len(flagged - {PRE}))
    listed_after = set()
    for fp in never:
        n = c.execute("select count(*) from cons_entry where fp=? and va>='2026-10-04 21:00:00' and policy in (?,?)",
                      (fp, NEAR, OURP)).fetchone()[0]
        if n:
            listed_after.add(fp)
    print("  never-flagged listed with attacker p line at/after 10-04 21:00:", len(listed_after),
          "family", sum(1 for f in listed_after if V[f]["family"] == "1"))
    lastva = collections.Counter()
    for fp in never:
        r = c.execute("select max(va) from cons_entry where fp=? and policy in (?,?)", (fp, NEAR, OURP)).fetchone()[0]
        lastva[r] += 1
    print("  never-flagged: last va with attacker p line:", sorted(lastva.items(), key=lambda x: str(x[0]))[-8:])
    vflag = set(f for (f,) in c.execute("select distinct fp from vote_entry where flags like '%BadExit%' "
                                         "or flags like '%MiddleOnly%'"))
    vnever = [fp for fp in V if fp not in vflag]
    print("  never flagged in any vote:", len(vnever), "family",
          sum(1 for f in vnever if V[f]["family"] == "1"))
    tord = [fp for fp in vnever if V[fp]["nickname"].startswith("TorDola")]
    print("  TorDola never vote-flagged:", tord)
    vabs = set(f for (f,) in c.execute("select distinct fp from vote_absent"))
    print("  flagged in a vote:", len(set(V) & vflag), "flagged or vote_absent:", len(set(V) & (vflag | vabs)))


def usable(c, V):
    vs = set(V)
    for (va,) in c.execute("select distinct va from cons_entry where va between '2026-10-04 20:00:00' "
                           "and '2026-10-05 17:00:00' order by va").fetchall():
        rows = c.execute("select fp, flags, policy from cons_entry where va=?", (va,)).fetchall()
        att = [r for r in rows if r[2] in ATT_P]
        ex = [r for r in att if " Exit " in " %s " % r[1]]
        use = [r for r in ex if "BadExit" not in r[1]]
        fl = [r for r in att if "BadExit" in r[1] or "MiddleOnly" in r[1]]
        print("usable:", va, "attacker", len(att), "Exit", len(ex), "usable", len(use), "flagged", len(fl),
              "usable victims", sum(1 for r in use if r[0] in vs))
    last = collections.defaultdict(str)
    for fp, va, flags, pol in c.execute("select fp, va, flags, policy from cons_entry where va>='2026-10-04 21:00:00'"):
        if pol in ATT_P and " Exit " in " %s " % flags and "BadExit" not in flags:
            last[fp] = max(last[fp], va)
    for fp, va in sorted(last.items(), key=lambda x: x[1]):
        print("  usable after 21:00:", fp, V.get(fp, {}).get("nickname"), "last", va)


def authfirst(c, V):
    vs = set(V) - {PRE}
    first = {}
    for va, auth, fp, flags in c.execute("select va, auth, fp, flags from vote_entry order by va"):
        if fp in vs and ("BadExit" in flags or "MiddleOnly" in flags) and auth not in first:
            first[auth] = va
    print("authfirst:", sorted(first.items(), key=lambda x: x[1]))


def nocontact(c, V):
    nc = [fp for fp, r in V.items() if r["operator"].strip() in ("", "(no contact line)")]
    print("nocontact:", len(nc), "hosts", len({V[f]["ip"] for f in nc}),
          [(f, V[f]["nickname"], V[f]["ip"]) for f in nc])


def rollback(c, V):
    rows = c.execute("select fp, published, old_class, new_class, kind from policy_event where published between "
                     "'2026-10-04 22:21:18' and '2026-10-04 22:47:33' order by published").fetchall()
    cnt = collections.Counter((r[2], r[3]) for r in rows)
    print("rollback:", len(rows), dict(cnt))


SECTIONS = {"fam1001": fam1001, "revert": revert, "flags": flags, "usable": usable,
            "authfirst": authfirst, "nocontact": nocontact, "rollback": rollback}


def main():
    c = conn()
    V = victims()
    for s in (sys.argv[1:] or list(SECTIONS)):
        SECTIONS[s](c, V)


if __name__ == "__main__":
    main()
