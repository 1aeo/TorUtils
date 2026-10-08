#!/usr/bin/env python3
"""email_current_status.py - current status of the 377 victim relays, as of the newest public data
(CollecTor "recent", fetched 2026-10-08), for the tor-relays follow-up email.

The network DB (net/netdb.sqlite) ends at consensus 2026-10-07 02:00:00 / descriptor 2026-10-07 02:18:04.
This script extends it with the CollecTor "recent" files downloaded into data_recent/ (every consensus
and server-descriptor file whose file-name timestamp is >= 2026-10-07 00:00:00):

  data_recent/consensuses/YYYY-MM-DD-HH-00-00-consensus
  data_recent/server-descriptors/YYYY-MM-DD-HH-MM-SS-server-descriptors
      (each file holds many descriptors, each starting with an "@type server-descriptor" line)

Parsing reuses scripts/build_netdb.py (parse_consensus: valid-after, r line base64 identity ->
40-hex uppercase, s flags, p line; parse_descriptor / desc_digest: fingerprint, published,
router address, accept/reject lines) and scripts/common.py (summarize_policy, a validated
re-implementation of tor's policy_summarize(), and classify_summary). Descriptors are de-duplicated by
digest. AS numbers come from the ip_as table (CAIDA RouteViews pfx2as 20261001-1200); an IP not in that
table is looked up in asdata/routeviews-rv2-20261001-1200.pfx2as.gz with scripts/asmap.py Pfx2AS.

Onionoo (onionoo_20261008/details.json, live, drops relays offline > 7 days) is used as a cross-check only.

Reports (stdout):
  * latest consensus valid-after; victims in it (flags, p line)
  * number of relays (any) in the latest consensus whose p line is near-open or OUR_POLICY
  * newest descriptor published time; victims that published any descriptor in the 24 h before it
    (published >= newest - 24 h), with the class of their newest descriptor
  * "online but excluded": victims whose newest descriptor (DB or recent files) is attacker-class
    (near-open / OUR_POLICY), published in that 24 h window, and that are absent from the latest consensus
  * victims silent: no descriptor published in the 24 h window (the recent files also carry descriptors
    published back to 2026-10-01, so "no descriptor in the recent files at all" is reported separately)
  * victims whose policy class changed in descriptors published after the DB end (2026-10-07 02:18:04)
  * relays NOT among the 377 that published a near-open / OUR_POLICY descriptor in the recent files
  * Onionoo running / last_seen summary for the victims

Writes net/email_current_status.csv (one row per victim):
  fp, nickname, ip, asn, family, last_desc_published, last_desc_class, in_latest_consensus, flags,
  onionoo_running, onionoo_last_seen, last_desc_source, last_recent_consensus_va, p_line
  (newest descriptor = the newer of net/victims.csv last_desc and the newest descriptor in data_recent/;
   last_desc_source = "recent" (only in data_recent/), "both" (same publication time in both) or "db";
   last_recent_consensus_va = newest of the 28 recent consensuses that lists the relay, empty if none;
   p_line = p line in the latest consensus, empty if not listed).
Also writes net/email_current_status_new_attacker_relays.csv (relays outside the 377, if any).

Usage: python3 -I scripts/email_current_status.py > net/email_current_status.log
"""
import collections
import csv
import datetime as dt
import glob
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import summarize_policy, classify_summary, ts_epoch, epoch_ts, NEAR_OPEN, OUR_POLICY  # noqa: E402
from build_netdb import parse_consensus, parse_descriptor, desc_digest  # noqa: E402
from asmap import Pfx2AS  # noqa: E402

ROOT = os.path.dirname(HERE)
RECENT = os.path.join(ROOT, "data_recent")
ONIONOO = os.path.join(ROOT, "onionoo_20261008", "details.json")
DB = os.path.join(ROOT, "net", "netdb.sqlite")
VICTIMS = os.path.join(ROOT, "net", "victims.csv")
SEEDS = os.path.join(ROOT, "family_seed_fingerprints.txt")
PFX2AS = os.path.join(ROOT, "asdata", "routeviews-rv2-20261001-1200.pfx2as.gz")
OUT = os.path.join(ROOT, "net", "email_current_status.csv")
OUT_NEW = os.path.join(ROOT, "net", "email_current_status_new_attacker_relays.csv")
FAMILY_CONTACT = "email:Quetzalcoatl_relays[]proton.me"
ATTACK = {"near-open", "OUR_POLICY"}
ATTACK_P = {NEAR_OPEN, OUR_POLICY}
DB_END = "2026-10-07 02:18:04"  # newest descriptor in net/netdb.sqlite


def split_descriptors(data):
    """Split a CollecTor server-descriptor file into single descriptors on '@type server-descriptor'."""
    parts = []
    marker = b"@type server-descriptor"
    pos = data.find(marker)
    if pos < 0:
        return [data] if data.strip() else []
    while pos >= 0:
        nxt = data.find(b"\n" + marker, pos + 1)
        end = len(data) if nxt < 0 else nxt + 1
        parts.append(data[pos:end])
        pos = -1 if nxt < 0 else nxt + 1
    return parts


def main():
    # ------------------------------------------------------------------ victims + family seeds
    victims = {r["fp"]: r for r in csv.DictReader(open(VICTIMS, newline=""))}
    seeds = set()
    for line in open(SEEDS):
        t = line.strip().upper()
        if len(t) == 40 and all(c in "0123456789ABCDEF" for c in t):
            seeds.add(t)
    print("victims:", len(victims), " family seeds:", len(seeds))

    # ------------------------------------------------------------------ consensuses
    cons = {}  # va -> {fp: entry}
    for path in sorted(glob.glob(os.path.join(RECENT, "consensuses", "*-consensus"))):
        va, entries = parse_consensus(open(path, "rb").read())
        cons[va] = {e[1]: e for e in entries}
    vas = sorted(cons)
    latest_va = vas[-1]
    latest = cons[latest_va]
    print("recent consensuses:", len(vas), vas[0], "..", latest_va, " relays in latest:", len(latest))
    last_cons_va = {}
    for va in vas:
        for fp in cons[va]:
            last_cons_va[fp] = va

    # relays (any) in the latest consensus with an attacker p line
    att_in_latest = sorted((fp, e[0], e[4], e[7], e[10]) for fp, e in latest.items() if e[10] in ATTACK_P)
    print("\n== relays in latest consensus (%s) with a near-open / OUR_POLICY p line: %d"
          % (latest_va, len(att_in_latest)))
    for row in att_in_latest:
        print("  ", row, "VICTIM" if row[0] in victims else "NOT-A-VICTIM")
    # per recent consensus: number of attacker p lines and victims listed
    print("\n== per recent consensus: relays, attacker p lines, victims listed")
    for va in vas:
        c = cons[va]
        print("  ", va, len(c), sum(1 for e in c.values() if e[10] in ATTACK_P),
              sum(1 for fp in c if fp in victims))

    # ------------------------------------------------------------------ server descriptors
    descs = {}  # digest -> dict
    n_raw = 0
    files = sorted(glob.glob(os.path.join(RECENT, "server-descriptors", "*-server-descriptors")))
    for path in files:
        data = open(path, "rb").read()
        for chunk in split_descriptors(data):
            n_raw += 1
            d = parse_descriptor(chunk)
            if "published" not in d or "fingerprint" not in d:
                continue
            dig = desc_digest(chunk) or ("NODIGEST-%s-%s" % (d["fingerprint"], d["published"]))
            if dig in descs:
                continue
            summ = summarize_policy(d["policy"])
            d["summary"] = summ
            d["class"] = classify_summary(summ)
            d["file"] = os.path.basename(path)
            descs[dig] = d
    print("\nserver-descriptor files:", len(files), " descriptors (raw):", n_raw, " unique digests:", len(descs))
    by_fp = collections.defaultdict(list)
    for d in descs.values():
        by_fp[d["fingerprint"]].append(d)
    for fp in by_fp:
        by_fp[fp].sort(key=lambda d: d["published"])
    pubs = sorted(d["published"] for d in descs.values())
    newest = pubs[-1]
    oldest = pubs[0]
    cutoff = epoch_ts(ts_epoch(newest) - 86400)
    print("descriptor published range:", oldest, "..", newest, " 24 h cutoff (>=):", cutoff,
          " relays with descriptors:", len(by_fp))

    # ------------------------------------------------------------------ AS lookup
    db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    ip_as = {}
    pfx = None

    def asn_of(ip):
        nonlocal pfx
        if ip in ip_as:
            return ip_as[ip]
        r = db.execute("SELECT asn, as_name FROM ip_as WHERE ip=?", (ip,)).fetchone()
        if r:
            ip_as[ip] = ("AS" + r[0].split("_")[0].split(",")[0], r[1], "ip_as")
        else:
            if pfx is None:
                pfx = Pfx2AS(PFX2AS)
            a, _ = pfx.lookup(ip)
            ip_as[ip] = (("AS" + a.split("_")[0].split(",")[0]) if a else "unmapped", "", "pfx2as")
        return ip_as[ip]

    # contact text for family check of non-victims
    def is_family(fp, contact):
        return fp in seeds or (contact or "").startswith(FAMILY_CONTACT)

    # ------------------------------------------------------------------ Onionoo
    oo = json.load(open(ONIONOO))
    oo_by = {r["fingerprint"]: r for r in oo["relays"]}
    print("\nOnionoo relays_published:", oo["relays_published"], " relays:", len(oo["relays"]))

    # ------------------------------------------------------------------ validation: summary vs consensus p line
    by_digest = {dig: d for dig, d in descs.items()}
    ok = bad = 0
    for fp, e in latest.items():
        d = by_digest.get(e[2])
        if d is None:
            continue
        if d["summary"] == e[10]:
            ok += 1
        else:
            bad += 1
    print("validation: latest-consensus entries whose descriptor (r-line digest) is in the recent files:",
          ok + bad, " p line == summarize_policy():", ok, " mismatches:", bad)

    # ------------------------------------------------------------------ per-victim status
    # newest descriptor per victim = the newer of (net/victims.csv last_desc, newest in data_recent/)
    rows = []
    in_latest = []
    published_24h = []
    online_excl = []
    reverted_excl = []
    silent_24h = []
    silent_after_db = []
    for fp in sorted(victims):
        v = victims[fp]
        ds = by_fp.get(fp, [])
        last = ds[-1] if ds else None
        if last is not None and last["published"] >= v["last_desc"]:
            ip, nick, pub, cls, src = last.get("address", ""), last.get("nickname", ""), last["published"], \
                last["class"], "recent" if last["published"] > v["last_desc"] else "both"
        else:
            ip, nick, pub, cls, src = v["ip"], v["nickname"], v["last_desc"], v["last_desc_class"], "db"
        if not any(d["published"] > DB_END for d in ds):
            silent_after_db.append(fp)
        asn = asn_of(ip)[0] if ip else v["asn"]
        e = latest.get(fp)
        if e:
            in_latest.append((fp, e[0], e[7], e[10]))
        if pub >= cutoff:
            published_24h.append((fp, cls))
            if not e:
                rec = dict(fp=fp, nickname=nick, ip=ip, asn=asn, as_name=asn_of(ip)[1] if ip else v["as_name"],
                           family=v["family"] == "1",
                           last_published=pub, policy_class=cls, last_recent_cons=last_cons_va.get(fp, ""),
                           n_desc_24h=sum(1 for d in ds if d["published"] >= cutoff),
                           summary=last["summary"] if last is not None and last["published"] == pub else "")
                (online_excl if cls in ATTACK else reverted_excl).append(rec)
        else:
            silent_24h.append(fp)
        o = oo_by.get(fp)
        rows.append([fp, nick, ip, asn, v["family"], pub, cls, 1 if e else 0, e[7] if e else "",
                     ("true" if o.get("running") else "false") if o else "not_in_onionoo",
                     o.get("last_seen", "") if o else "", src, last_cons_va.get(fp, ""), e[10] if e else ""])

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "nickname", "ip", "asn", "family", "last_desc_published", "last_desc_class",
                    "in_latest_consensus", "flags", "onionoo_running", "onionoo_last_seen",
                    "last_desc_source", "last_recent_consensus_va", "p_line"])
        w.writerows(rows)
    print("wrote", OUT, len(rows), "rows")

    print("\n== victims in latest consensus %s: %d" % (latest_va, len(in_latest)))
    for x in in_latest:
        print("  ", x)
    print("\n== victims with any descriptor in recent files (any published time):",
          sum(1 for fp in victims if fp in by_fp))
    print("== victims publishing in last 24 h (published >= %s): %d" % (cutoff, len(published_24h)))
    print("   class of newest descriptor:", dict(collections.Counter(c for _, c in published_24h)))
    print("   of which attacker-class:", sum(1 for _, c in published_24h if c in ATTACK))
    print("\n== online but excluded (attacker-class newest descriptor in last 24 h, not in latest consensus):",
          len(online_excl))
    for x in sorted(online_excl, key=lambda x: x["last_published"]):
        print("  ", {k: x[k] for k in x if k != "summary"})
    print("   by class:", dict(collections.Counter(x["policy_class"] for x in online_excl)),
          " by asn:", dict(collections.Counter(x["asn"] for x in online_excl)),
          " family:", sum(1 for x in online_excl if x["family"]),
          " in any recent consensus:", sum(1 for x in online_excl if x["last_recent_cons"]))
    ops = collections.Counter(victims[x["fp"]]["operator"] for x in online_excl)
    print("   distinct operators (exact contact string):", len(ops))
    for op, n in ops.most_common():
        print("     %2d  %s" % (n, op[:120]))
    print("   AS names:", dict(collections.Counter("%s %s" % (x["asn"], x["as_name"]) for x in online_excl)))
    print("\n== publishing a NON-attacker policy in last 24 h but not in latest consensus:", len(reverted_excl))
    for x in sorted(reverted_excl, key=lambda x: x["last_published"]):
        print("  ", x)
    print("   by class:", dict(collections.Counter(x["policy_class"] for x in reverted_excl)),
          " in any recent consensus:", sum(1 for x in reverted_excl if x["last_recent_cons"]))
    print("\n== victims silent: no descriptor published in the last 24 h:", len(silent_24h),
          " family:", sum(1 for fp in silent_24h if victims[fp]["family"] == "1"))
    print("   newest descriptor class of those:",
          dict(collections.Counter(r[6] for r in rows if r[0] in set(silent_24h))))
    print("   newest descriptor date of those:",
          dict(sorted(collections.Counter(r[5][:10] for r in rows if r[0] in set(silent_24h)).items())))
    print("== victims with no descriptor published after the DB end (%s) in the recent files: %d (family %d)"
          % (DB_END, len(silent_after_db), sum(1 for fp in silent_after_db if victims[fp]["family"] == "1")))
    print("== previous 24 h set (net/victims.csv: attacker last_desc >= 2026-10-06 02:18:04):")
    prev = {fp for fp, v in victims.items() if v["last_desc_is_attacker"] == "1" and v["last_desc"] >= "2026-10-06 02:18:04"}
    now = {x["fp"] for x in online_excl}
    print("   previous:", len(prev), " now:", len(now), " in both:", len(prev & now))
    for fp in sorted(prev - now):
        r = next(r for r in rows if r[0] == fp)
        print("   stopped/changed:", fp, r[1], r[2], r[3], r[5], r[6])
    for fp in sorted(now - prev):
        r = next(r for r in rows if r[0] == fp)
        print("   newly in set   :", fp, r[1], r[2], r[3], r[5], r[6], "DB last_desc:", victims[fp]["last_desc"],
              victims[fp]["last_desc_class"])

    # ------------------------------------------------------------------ class changes after the DB end
    print("\n== victims whose policy class changed in descriptors published after %s" % DB_END)
    for fp in sorted(victims):
        post = [d for d in by_fp.get(fp, []) if d["published"] > DB_END]
        if not post:
            continue
        seq = [victims[fp]["last_desc_class"]] + [d["class"] for d in post]
        if len(set(seq)) == 1:
            continue
        print("  ", fp, victims[fp]["nickname"], "DB last:", victims[fp]["last_desc"], victims[fp]["last_desc_class"])
        prev = victims[fp]["last_desc_class"]
        for d in post:
            if d["class"] != prev:
                up = d.get("uptime")
                boot = epoch_ts(ts_epoch(d["published"]) - up) if isinstance(up, int) else "?"
                print("      %s -> %s at %s (uptime %s s, boot ~%s, platform %s)"
                      % (prev, d["class"], d["published"], up, boot, d.get("platform")))
                prev = d["class"]

    # ------------------------------------------------------------------ new attacker-policy relays
    new = []
    for fp, ds in by_fp.items():
        if fp in victims:
            continue
        att = [d for d in ds if d["class"] in ATTACK]
        if not att:
            continue
        last = ds[-1]
        in_db = db.execute("SELECT count(*), min(published), max(published) FROM descriptor WHERE fp=?",
                           (fp,)).fetchone()
        new.append(dict(fp=fp, nickname=last.get("nickname"), ip=last.get("address"),
                        asn=asn_of(last.get("address", ""))[0], contact=last.get("contact", ""),
                        family=is_family(fp, last.get("contact")),
                        first_attacker_published=att[0]["published"], last_published=last["published"],
                        last_class=last["class"], attacker_classes=sorted({d["class"] for d in att}),
                        in_latest_consensus=fp in latest, desc_in_db=in_db[0], db_first=in_db[1],
                        db_last=in_db[2]))
    print("\n== relays NOT among the 377 with a near-open / OUR_POLICY descriptor in recent files:", len(new))
    for x in sorted(new, key=lambda x: x["first_attacker_published"]):
        print("  ", x)
    with open(OUT_NEW, "w", newline="") as f:
        w = csv.writer(f)
        cols = ["fp", "nickname", "ip", "asn", "family", "contact", "first_attacker_published",
                "last_published", "last_class", "attacker_classes", "in_latest_consensus", "desc_in_db",
                "db_first", "db_last"]
        w.writerow(cols)
        for x in sorted(new, key=lambda x: x["first_attacker_published"]):
            w.writerow([x[c] if c != "attacker_classes" else " ".join(x[c]) for c in cols])
    print("wrote", OUT_NEW, len(new), "rows")
    # also: non-victims with attacker p line in any recent consensus
    nv = sorted({fp for va in vas for fp, e in cons[va].items() if e[10] in ATTACK_P and fp not in victims})
    print("non-victims with attacker p line in any recent consensus:", len(nv), nv)

    # ------------------------------------------------------------------ Onionoo summary
    st = collections.Counter()
    ls = collections.Counter()
    oo_att = []
    for fp in victims:
        o = oo_by.get(fp)
        if not o:
            st["not_in_onionoo"] += 1
            print("   victim not in Onionoo:", fp, victims[fp]["nickname"], victims[fp]["ip"],
                  "last_consensus_va (DB):", victims[fp]["last_consensus_va"])
            continue
        st["running" if o.get("running") else "not_running"] += 1
        ls[o.get("last_seen", "")[:10]] += 1
        eps = o.get("exit_policy_summary") or {}
        if o.get("running"):
            oo_att.append((fp, o.get("nickname"), o.get("last_seen"), " ".join(o.get("flags", [])), json.dumps(eps)))
    print("\n== Onionoo (relays_published %s) for the 377 victims:" % oo["relays_published"], dict(st))
    print("   last_seen date distribution:", dict(sorted(ls.items())))
    fam_ls = collections.Counter()
    for fp in victims:
        o = oo_by.get(fp)
        fam_ls[(victims[fp]["family"], "in" if o else "absent", (o or {}).get("running"))] += 1
    print("   (family, presence, running):", dict(fam_ls))
    print("   running victims:")
    for x in oo_att:
        print("    ", x)
    # max last_seen for victims not running
    nr = [oo_by[fp].get("last_seen") for fp in victims if fp in oo_by and not oo_by[fp].get("running")]
    if nr:
        print("   not-running victims last_seen range:", min(nr), "..", max(nr))
    # Onionoo vs latest consensus agreement for victims
    dis = [fp for fp in victims if (fp in latest) != bool(oo_by.get(fp, {}).get("running"))]
    print("   victims where Onionoo running != listed in latest consensus:", len(dis), dis)
    # attacker summaries in Onionoo for running relays (any)
    def oo_summary_str(eps):
        if "reject" in eps:
            return "reject " + ",".join(eps["reject"])
        if "accept" in eps:
            return "accept " + ",".join(eps["accept"])
        return ""
    oo_running_att = [r["fingerprint"] for r in oo["relays"] if r.get("running")
                      and oo_summary_str(r.get("exit_policy_summary") or {}) in ATTACK_P]
    print("   Onionoo running relays (any) with attacker exit_policy_summary:", len(oo_running_att), oo_running_att)


if __name__ == "__main__":
    main()
