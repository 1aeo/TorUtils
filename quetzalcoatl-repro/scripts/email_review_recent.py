"""email_review_recent.py - independent re-check of the draft's current-status lines.

Parses data_recent/ (CollecTor recent/ consensuses and server descriptors, downloaded
2026-10-08) with its own minimal parser, and reports for the 377 victims (DB table victim):
  * per recent consensus: attacker p lines, victims listed (with flags and p line);
  * descriptors published in the 24 h before the newest descriptor: which victims published,
    which published any attacker-policy descriptor, newest class, FranTech / family split;
  * victims with no descriptor in that window.
AS from net/netdb.sqlite ip_as (CAIDA).  Standard library only; run as
"python3 -I scripts/email_review_recent.py".
"""
import base64
import collections
import datetime as dt
import glob
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATT = {common.NEAR_OPEN: "near-open", common.OUR_POLICY: "OUR_POLICY"}


def b64fp(s):
    return base64.b64decode(s + "=" * (-len(s) % 4)).hex().upper()


def main():
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(ROOT, "net", "netdb.sqlite"), uri=True)
    V = {r[0] for r in c.execute("select fp from victim")}
    seeds = {l.split()[0].upper() for l in open(os.path.join(ROOT, "family_seed_fingerprints.txt"))
             if l.strip() and not l.startswith("#")}
    famc = [h for h, t in c.execute("select contact_h, text from contact")
            if t and t.startswith("email:Quetzalcoatl_relays[]proton.me")]
    fam = seeds | {r[0] for r in c.execute(
        "select distinct fp from descriptor where contact_h in (%s)" % ",".join("?" * len(famc)), famc)}

    def asn(ip):
        r = c.execute("select asn from ip_as where ip=?", (ip,)).fetchone()
        return r[0] if r else None

    # consensuses
    cons_files = sorted(glob.glob(os.path.join(ROOT, "data_recent", "consensuses", "*-consensus")))
    any_att = 0
    victims_listed = collections.Counter()
    last = None
    for p in cons_files:
        va = None
        entries = []
        cur = None
        for line in open(p, encoding="utf-8", errors="replace"):
            if line.startswith("valid-after "):
                va = line[12:31]
            elif line.startswith("r "):
                f = line.split()
                cur = {"fp": b64fp(f[2]), "nick": f[1], "ip": f[6]}
                entries.append(cur)
            elif line.startswith("s ") and cur is not None:
                cur["flags"] = line[2:].strip()
            elif line.startswith("p ") and cur is not None:
                cur["p"] = line[2:].strip()
        att = [e for e in entries if e.get("p") in ATT]
        vl = [e for e in entries if e["fp"] in V]
        any_att += len(att)
        for e in vl:
            victims_listed[e["fp"]] += 1
        last = (va, len(entries), len(att), vl)
    print("recent consensuses:", len(cons_files), "attacker p lines in all:", any_att)
    print("victims listed in any recent consensus:", dict(victims_listed))
    print("latest:", last[0], "entries", last[1], "attacker p lines", last[2])
    for e in last[3]:
        print("   victim in latest:", e)

    # server descriptors
    descs = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data_recent", "server-descriptors", "*-server-descriptors"))):
        data = open(p, "rb").read()
        for chunk in data.split(b"@type server-descriptor 1.0\n"):
            if not chunk.strip():
                continue
            i = chunk.find(b"router ")
            j = chunk.find(b"\nrouter-signature\n")
            if i < 0 or j < 0:
                continue
            body = chunk[i:j + len(b"\nrouter-signature\n")]
            dg = hashlib.sha1(body).hexdigest().upper()
            if dg in descs:
                continue
            fp = pub = ip = None
            pol = []
            for line in body.decode("utf-8", "replace").split("\n"):
                if line.startswith("router "):
                    ip = line.split()[2]
                elif line.startswith("fingerprint "):
                    fp = line[12:].replace(" ", "").upper()
                elif line.startswith("published "):
                    pub = line[10:29]
                elif line.startswith("accept ") or line.startswith("reject "):
                    pol.append(line)
            descs[dg] = (fp, pub, ip, common.classify_summary(common.summarize_policy(pol)))
    print("recent descriptors unique:", len(descs))
    newest = max(d[1] for d in descs.values())
    t0 = (dt.datetime.strptime(newest, common.TS_FMT) - dt.timedelta(hours=24)).strftime(common.TS_FMT)
    print("newest descriptor:", newest, "window start:", t0)
    byfp = collections.defaultdict(list)
    for dg, d in descs.items():
        byfp[d[0]].append(d)
    pub_v = {fp for fp in V if any(d[1] >= t0 for d in byfp.get(fp, []))}
    att_any = {fp for fp in V if any(d[1] >= t0 and d[3] in ATT.values() for d in byfp.get(fp, []))}
    newest_cls = {}
    for fp in pub_v:
        dd = sorted(d for d in byfp[fp] if d[1] >= t0)
        newest_cls[fp] = (dd[-1][3], dd[-1][2], dd[-1][1])
    att_newest = {fp for fp, x in newest_cls.items() if x[0] in ATT.values()}
    print("victims publishing in window:", len(pub_v), "family:", len(pub_v & fam))
    print("victims with any attacker descriptor in window:", len(att_any), "newest attacker:", len(att_newest))
    print("  any-but-not-newest:", sorted(att_any - att_newest))
    print("  newest classes:", collections.Counter(x[0] for x in newest_cls.values()))
    print("  attacker-newest by AS:", collections.Counter(asn(newest_cls[fp][1]) for fp in att_newest),
          "family:", len(att_newest & fam))
    print("  any-attacker by AS:", collections.Counter(asn(sorted(d for d in byfp[fp] if d[1] >= t0)[-1][2]) for fp in att_any))
    silent = V - pub_v
    print("victims with no descriptor in window:", len(silent), "family:", len(silent & fam), "all family silent:", fam & V <= silent)
    # any victim descriptor after DB end (2026-10-07 02:18:04)
    after = {fp for fp in V if any(d[1] > "2026-10-07 02:18:04" for d in byfp.get(fp, []))}
    print("victims with a descriptor published after 2026-10-07 02:18:04:", len(after), "family:", len(after & fam))
    fam_last = max((d[1] for fp in fam & V for d in byfp.get(fp, [])), default=None)
    print("newest family-victim descriptor in recent files:", fam_last)
    # new attacker relays outside the victim set
    newatt = {d[0] for d in descs.values() if d[3] in ATT.values() and d[0] not in V}
    print("non-victim relays with attacker descriptors in recent files:", len(newatt))


if __name__ == "__main__":
    main()
