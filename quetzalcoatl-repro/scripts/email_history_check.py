#!/usr/bin/env python3
"""email_history_check.py - history check for the claim "this exit policy never appeared before in 2026".

For the tor-relays follow-up email. The network DB (net/netdb.sqlite) covers CollecTor May-Oct 2026 and
already shows zero near-open / OUR_POLICY descriptors before 2026-10-01. This script extends the check
backwards with archives downloaded into data_history/ (server-descriptors-2026-01..04,
consensuses-2025-01..2026-04) and re-states the DB window with the same tests, so one CSV covers all.

Archives are streamed (tarfile mode "r|xz"), never extracted. One worker process per archive, at most
3 at a time (multiprocessing.Pool(3)).

Server descriptors - for every descriptor, the accept/reject lines are tested:
  (a) ourpolicy_sequence: after dropping ignored lines, the rules are exactly, in this order,
      reject *:25, *:465, *:587, *:110, *:143, *:993, *:995, *:3389, *:135, *:137-139, *:445, accept *:*
  (b) nearopen_sequence:  exactly reject *:25, *:465, *:587, *:993, *:995, *:119, *:135-139, *:445,
      *:563, *:1214, *:4661-4666, *:6346-6429, *:6699, *:6881-6999, accept *:*
      Ignored lines (tor's ExitPolicyRejectPrivate output): "reject" rules whose network is one of tor's
      private nets (0/8, 169.254/16, 127/8, 192.168/16, 10/8, 172.16/12) and "reject <single IPv4>:*"
      rules (/32, all ports; tor adds the relay's own addresses). For each match it is recorded whether
      every ignored /32 equals the relay's own router / or-address IPv4 address.
  (a2)/(b2) *_set: same rules as (a)/(b) in any order (no duplicates, nothing else)
  (c) loose_rules: the policy contains the literal lines "reject *:110", "reject *:143" and "reject *:3389"
  (d) ourpolicy_summary / nearopen_summary: scripts/common.py summarize_policy() (validated
      re-implementation of tor's policy_summarize) equals OUR_POLICY / near-open; cached by sha1 of the
      policy text.
  (e) loose_summary: the summary is an exit's reject list (not "reject 1-65535") that rejects all of
      110, 143 and 3389.
Consensuses - every "p" line (the summary the authorities publish for each LISTED relay) is compared with
  "p " + OUR_POLICY / "p " + near-open; loose_summary as (e). A relay only has a p line while it is listed.

Per archive it also reports the summary (descriptor summary / consensus p line) closest to OUR_POLICY and
to near-open, measured as the number of ports 1-65535 whose accept/reject status differs (in DB consensus
rows the n of that column counts cons_interval rows, not entries).
Per archive it also records coverage: descriptors / consensus entries scanned, unique fingerprints,
min/max published (or valid-after), consensus hours present / missing, days without descriptors.

--db PATH adds rows for the DB window (CollecTor May-Oct 2026), computed from tables descriptor+policy
(same tests (a)-(e), applied to each policy text) and consensus.counts (pol:OUR_POLICY / pol:near-open
counts of p-line classes per consensus; the loose test and unique fingerprints are n/a there).

Usage (from quetzalcoatl-repro/):
  python3 -I scripts/email_history_check.py --db net/netdb.sqlite --out net/email_history_check.csv \
      --matches net/email_history_check_matches.csv data_history/*.tar.xz
Writes the CSV (one row per archive month and source) and a matches CSV (first descriptor / consensus
entry per fingerprint and test), and prints a summary with the earliest example of each test.
"""
import argparse
import ast
import collections
import csv
import datetime as dt
import hashlib
import ipaddress
import multiprocessing
import os
import re
import sqlite3
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NEAR_OPEN, OUR_POLICY, PRIVATE_NETS_V4, b64_to_hex,  # noqa: E402
                    parse_policy_line, summarize_policy)

OUR_SEQ = ["reject *:%s" % p for p in ("25", "465", "587", "110", "143", "993", "995", "3389", "135",
                                         "137-139", "445")] + ["accept *:*"]
NEAR_SEQ = ["reject *:%s" % p for p in ("25", "465", "587", "993", "995", "119", "135-139", "445", "563",
                                          "1214", "4661-4666", "6346-6429", "6699", "6881-6999")] + ["accept *:*"]
LOOSE_LINES = ("reject *:110", "reject *:143", "reject *:3389")
DESC_TESTS = ("ourpolicy_sequence", "nearopen_sequence", "ourpolicy_set", "nearopen_set",
              "loose_rules_110_143_3389", "ourpolicy_summary", "nearopen_summary", "loose_summary_110_143_3389")
CONS_TESTS = ("ourpolicy_summary", "nearopen_summary", "loose_summary_110_143_3389")
ALL_TESTS = DESC_TESTS

RE_ROUTER_START = re.compile(rb"(?m)^router ")
RE_ROUTER = re.compile(rb"(?m)^router (\S+) (\S+)")
RE_FP = re.compile(rb"(?m)^fingerprint ([0-9A-Fa-f ]+)\s*$")
RE_PUB = re.compile(rb"(?m)^published (\S+ \S+)")
RE_POL = re.compile(rb"(?m)^(?:accept|reject) [^\n]*")
RE_ORADDR = re.compile(rb"(?m)^or-address (\S+)")
RE_VA = re.compile(rb"(?m)^valid-after (\S+ \S+)")
RE_P = re.compile(rb"(?m)^p ([^\n]*)")
RE_R = re.compile(rb"(?m)^r ")


def rejects_all(summary, ports=(110, 143, 3389)):
    """True if summary is an exit's reject list ("reject a,b-c,...", not the non-exit "reject 1-65535")
    covering every port in ports."""
    if not summary.startswith("reject ") or summary.strip() == "reject 1-65535":
        return False
    rng = []
    for part in summary[7:].split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            rng.append((int(a), int(b) if b else int(a)))
        except ValueError:
            return False
    return all(any(lo <= p <= hi for lo, hi in rng) for p in ports)


FULL_MASK = ((1 << 65535) - 1) << 1  # bits 1..65535


def rejected_mask(summary):
    """int bitmask of the ports a summary rejects (bit p set = port p rejected)."""
    kind, _, plist = summary.strip().partition(" ")
    m = 0
    for part in plist.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a), int(b) if b else int(a)
        except ValueError:
            continue
        m |= ((1 << (hi - lo + 1)) - 1) << lo
    m &= FULL_MASK
    return m if kind == "reject" else FULL_MASK & ~m


OUR_MASK = rejected_mask(OUR_POLICY)
NEAR_MASK = rejected_mask(NEAR_OPEN)


def closest(summary_counts):
    """For a Counter {summary: n}, the summary nearest to OUR_POLICY and to near-open, measured as the
    number of ports whose accept/reject status differs. Returns two strings 'ports_differing=D n=N <summary>'."""
    out = []
    for target in (OUR_MASK, NEAR_MASK):
        best = None
        for sm, n in summary_counts.items():
            if not sm:
                continue
            d = (rejected_mask(sm) ^ target).bit_count()
            k = (d, -n, sm)
            if best is None or k < best:
                best = k
        out.append("ports_differing=%d n=%d %s" % (best[0], -best[1], best[2]) if best else "")
    return out


def analyse_policy(lines):
    """lines: list of str policy lines. Returns (dict test->bool, summary, tuple of ignored /32 IPs)."""
    kept, ign32 = [], []
    for raw in lines:
        line = " ".join(raw.split())
        it = parse_policy_line(line)
        if it is not None and it[0] == "reject":
            _, net, bits, pmin, pmax = it
            if (net, bits) in PRIVATE_NETS_V4:
                continue
            if bits == 32 and pmin == 1 and pmax == 65535:
                ign32.append(str(ipaddress.IPv4Address(net)))
                continue
        kept.append(line)
    summ = summarize_policy([" ".join(x.split()) for x in lines])
    lineset = set(" ".join(x.split()) for x in lines)
    res = {
        "ourpolicy_sequence": kept == OUR_SEQ,
        "nearopen_sequence": kept == NEAR_SEQ,
        "ourpolicy_set": len(kept) == len(OUR_SEQ) and set(kept) == set(OUR_SEQ),
        "nearopen_set": len(kept) == len(NEAR_SEQ) and set(kept) == set(NEAR_SEQ),
        "loose_rules_110_143_3389": all(x in lineset for x in LOOSE_LINES),
        "ourpolicy_summary": summ == OUR_POLICY,
        "nearopen_summary": summ == NEAR_OPEN,
        "loose_summary_110_143_3389": rejects_all(summ),
    }
    return res, summ, tuple(ign32)


def month_of(path):
    m = re.search(r"(\d{4}-\d\d)\.tar\.xz$", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def new_stats():
    return {"items": 0, "fps": set(), "tmin": None, "tmax": None,
            "count": collections.Counter(), "tfps": collections.defaultdict(set),
            "first": {}, "matches": {}, "errors": 0, "error_msg": "", "members": 0,
            "summaries": collections.Counter()}


def note(st, test, t, fp, nick, addr, extra):
    st["count"][test] += 1
    st["tfps"][test].add(fp)
    e = (t, fp, nick, addr, extra)
    if test not in st["first"] or e < st["first"][test]:
        st["first"][test] = e
    k = (test, fp)
    if k not in st["matches"] or e < st["matches"][k]:
        st["matches"][k] = e


def desc_worker(path):
    st = new_stats()
    cache = {}
    days = set()
    names = set()
    try:
        with tarfile.open(path, mode="r|xz") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                data = f.read()
                st["members"] += 1
                names.add(m.name.rsplit("/", 1)[-1])
                starts = [x.start() for x in RE_ROUTER_START.finditer(data)]
                if not starts:
                    st["errors"] += 1
                    continue
                bounds = starts[1:] + [len(data)]
                for s, e in zip(starts, bounds):
                    d = data[s:e]
                    rt = RE_ROUTER.search(d)
                    fpm = RE_FP.search(d)
                    pub = RE_PUB.search(d)
                    if not (rt and fpm and pub):
                        st["errors"] += 1
                        continue
                    fp = fpm.group(1).replace(b" ", b"").decode().upper()
                    published = pub.group(1).decode()
                    nick = rt.group(1).decode("utf-8", "replace")
                    addr = rt.group(2).decode("utf-8", "replace")
                    st["items"] += 1
                    st["fps"].add(fp)
                    days.add(published[:10])
                    if st["tmin"] is None or published < st["tmin"]:
                        st["tmin"] = published
                    if st["tmax"] is None or published > st["tmax"]:
                        st["tmax"] = published
                    pol = RE_POL.findall(d)
                    key = hashlib.sha1(b"\n".join(pol)).digest()
                    r = cache.get(key)
                    if r is None:
                        r = analyse_policy([x.decode("utf-8", "replace") for x in pol])
                        cache[key] = r
                    res, summ, ign32 = r
                    st["summaries"][summ] += 1
                    if not any(res.values()):
                        continue
                    own = {addr}
                    for oa in RE_ORADDR.findall(d):
                        oa = oa.decode("utf-8", "replace")
                        if not oa.startswith("["):
                            own.add(oa.rsplit(":", 1)[0])
                    own_ok = all(ip in own for ip in ign32)
                    extra = "summary=%s; ignored_32=%s; own_ip_ok=%s" % (summ, "|".join(ign32), own_ok)
                    for test, ok in res.items():
                        if ok:
                            note(st, test, published, fp, nick, addr, extra)
    except Exception as ex:  # truncated / corrupt archive: report, do not hide
        st["errors"] += 1
        st["error_msg"] = "%s: %s" % (type(ex).__name__, ex)
    st["unique_member_names"] = len(names)
    st["unique_policy_texts"] = len(cache)
    mo = month_of(path)
    y, mm = int(mo[:4]), int(mo[5:7])
    d0 = dt.date(y, mm, 1)
    d1 = dt.date(y + (mm == 12), mm % 12 + 1, 1)
    missing = []
    while d0 < d1:
        if d0.isoformat() not in days:
            missing.append(d0.isoformat())
        d0 += dt.timedelta(days=1)
    st["coverage_gaps"] = "days_without_descriptors=%d %s" % (len(missing), " ".join(missing))
    return finish(path, "server-descriptors", st)


def cons_worker(path):
    st = new_stats()
    vas = set()
    pcount = collections.Counter()
    targets = {"ourpolicy_summary": b"p " + OUR_POLICY.encode(), "nearopen_summary": b"p " + NEAR_OPEN.encode()}
    loose_cache = {}
    try:
        with tarfile.open(path, mode="r|xz") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                data = f.read()
                st["members"] += 1
                vam = RE_VA.search(data)
                if not vam:
                    st["errors"] += 1
                    continue
                va = vam.group(1).decode()
                vas.add(va)
                if st["tmin"] is None or va < st["tmin"]:
                    st["tmin"] = va
                if st["tmax"] is None or va > st["tmax"]:
                    st["tmax"] = va
                n_r = len(RE_R.findall(data))
                ps = RE_P.findall(data)
                st["items"] += n_r
                st["p_lines"] = st.get("p_lines", 0) + len(ps)
                pc = collections.Counter(ps)
                pcount.update(pc)
                hit = {}
                for pv in pc:
                    s = pv.decode("utf-8", "replace").strip()
                    lz = loose_cache.get(s)
                    if lz is None:
                        lz = rejects_all(s)
                        loose_cache[s] = lz
                    res = {"ourpolicy_summary": s == OUR_POLICY, "nearopen_summary": s == NEAR_OPEN,
                           "loose_summary_110_143_3389": lz}
                    if any(res.values()):
                        hit[pv] = res
                if not hit:
                    # still collect fingerprints for coverage
                    for rl in re.findall(rb"(?m)^r \S+ (\S+) ", data):
                        st["fps"].add(rl)
                    continue
                cur = None
                for line in data.split(b"\n"):
                    if line.startswith(b"r "):
                        p = line.split()
                        cur = (b64_to_hex(p[2].decode()), p[1].decode("utf-8", "replace"), p[6].decode())
                        st["fps"].add(p[2])
                    elif line.startswith(b"p ") and cur is not None:
                        res = hit.get(line[2:])
                        if res:
                            for test, ok in res.items():
                                if ok:
                                    note(st, test, va, cur[0], cur[1], cur[2], "p " + line[2:].decode())
    except Exception as ex:
        st["errors"] += 1
        st["error_msg"] = "%s: %s" % (type(ex).__name__, ex)
    st["unique_policy_texts"] = len(pcount)
    for pv, n in pcount.items():
        st["summaries"][pv.decode("utf-8", "replace").strip()] += n
    st["unique_member_names"] = st["members"]
    st["n_consensuses"] = len(vas)
    mo = month_of(path)
    y, mm = int(mo[:4]), int(mo[5:7])
    t = dt.datetime(y, mm, 1)
    t1 = dt.datetime(y + (mm == 12), mm % 12 + 1, 1)
    missing = []
    while t < t1:
        if t.strftime("%Y-%m-%d %H:%M:%S") not in vas:
            missing.append(t.strftime("%Y-%m-%dT%H"))
        t += dt.timedelta(hours=1)
    st["coverage_gaps"] = "hours_missing=%d %s" % (len(missing), " ".join(missing))
    return finish(path, "consensuses", st)


def finish(path, source, st):
    """Turn sets into counts so the result pickles small."""
    out = {"month": month_of(path), "source": source, "archive": os.path.basename(path),
           "archive_bytes": os.path.getsize(path), "items_scanned": st["items"],
           "unique_fps": len(st["fps"]), "tmin": st["tmin"], "tmax": st["tmax"],
           "members": st["members"], "unique_member_names": st.get("unique_member_names", ""),
           "unique_policy_texts": st.get("unique_policy_texts", ""),
           "n_consensuses": st.get("n_consensuses", ""), "p_lines": st.get("p_lines", ""),
           "coverage_gaps": st.get("coverage_gaps", ""), "errors": st["errors"], "error_msg": st["error_msg"],
           "count": dict(st["count"]), "ufps": {k: len(v) for k, v in st["tfps"].items()},
           "first": st["first"], "matches": st["matches"]}
    out["closest_ourpolicy"], out["closest_nearopen"] = closest(st["summaries"])
    out["distinct_summaries"] = len(st["summaries"])
    return out


def run(path):
    name = os.path.basename(path)
    if name.startswith("server-descriptors-"):
        return desc_worker(path)
    if name.startswith("consensuses-"):
        return cons_worker(path)
    raise SystemExit("unknown archive " + path)


def db_rows(dbpath):
    """Rows for the DB window, per month, from descriptor+policy and consensus.counts."""
    db = sqlite3.connect("file:%s?mode=ro" % dbpath, uri=True)
    pol = {}
    for h, text in db.execute("SELECT policy_h, text FROM policy"):
        res, summ, ign32 = analyse_policy(text.split("\n") if text else [])
        pol[h] = (res, summ, ign32)
    rows = {}
    q = "SELECT substr(published,1,7), fp, published, nickname, address, policy_h, or_addresses FROM descriptor"
    for mo, fp, pub, nick, addr, ph, oas in db.execute(q):
        st = rows.setdefault(("db:" + mo, "server-descriptors"), new_stats())
        st["items"] += 1
        st["fps"].add(fp)
        if st["tmin"] is None or pub < st["tmin"]:
            st["tmin"] = pub
        if st["tmax"] is None or pub > st["tmax"]:
            st["tmax"] = pub
        r = pol.get(ph)
        if r is not None:
            st["summaries"][r[1]] += 1
        if r is None or not any(r[0].values()):
            continue
        res, summ, ign32 = r
        own = {addr} | {x.rsplit(":", 1)[0] for x in (oas or "").replace(",", " ").split() if not x.startswith("[")}
        extra = "summary=%s; ignored_32=%s; own_ip_ok=%s" % (summ, "|".join(ign32), all(i in own for i in ign32))
        for test, ok in res.items():
            if ok:
                note(st, test, pub, fp, nick, addr, extra)
    for va, n, counts in db.execute("SELECT va, n, counts FROM consensus"):
        st = rows.setdefault(("db:" + va[:7], "consensuses"), new_stats())
        d = ast.literal_eval(counts)
        st["items"] += n
        st["n_consensuses"] = st.get("n_consensuses", 0) + 1
        if st["tmin"] is None or va < st["tmin"]:
            st["tmin"] = va
        if st["tmax"] is None or va > st["tmax"]:
            st["tmax"] = va
        for test, k in (("ourpolicy_summary", "pol:OUR_POLICY"), ("nearopen_summary", "pol:near-open")):
            c = d.get(k, 0)
            if c:
                st["count"][test] += c
                if test not in st["first"] or va < st["first"][test][0]:
                    st["first"][test] = (va, "", "", "", "from consensus.counts")
    # earliest listed relay per class from cons_entry (valid-after >= 2026-09-24 only)
    for test, s in (("ourpolicy_summary", OUR_POLICY), ("nearopen_summary", NEAR_OPEN)):
        r = db.execute("SELECT va, fp, nickname, ip FROM cons_entry WHERE policy=? ORDER BY va, fp LIMIT 1",
                       (s,)).fetchone()
        if r:
            st = rows[("db:" + r[0][:7], "consensuses")]
            st["first"][test] = (r[0], r[1], r[2], r[3], "p " + s)
        for va, fp, nick, ip in db.execute("SELECT va, fp, nickname, ip FROM cons_entry WHERE policy=?", (s,)):
            st = rows[("db:" + va[:7], "consensuses")]
            st["tfps"][test].add(fp)
            k = (test, fp)
            e = (va, fp, nick, ip, "p " + s)
            if k not in st["matches"] or e < st["matches"][k]:
                st["matches"][k] = e
    for mo_key, source in list(rows):
        if source != "consensuses":
            continue
        mo = mo_key[3:]
        y, mm = int(mo[:4]), int(mo[5:7])
        m0 = "%04d-%02d-01 00:00:00" % (y, mm)
        m1 = "%04d-%02d-01 00:00:00" % (y + (mm == 12), mm % 12 + 1)
        st = rows[(mo_key, source)]
        for pv, n in db.execute("SELECT policy, count(*) FROM cons_interval WHERE start_va < ? AND end_va >= ? "
                                "GROUP BY policy", (m1, m0)):
            st["summaries"][pv or ""] += n
    out = []
    for (mo, source), st in sorted(rows.items()):
        o = {"month": mo, "source": source, "archive": "net/netdb.sqlite", "archive_bytes": "",
             "items_scanned": st["items"], "unique_fps": len(st["fps"]), "tmin": st["tmin"], "tmax": st["tmax"],
             "members": "", "unique_member_names": "", "unique_policy_texts": "",
             "n_consensuses": st.get("n_consensuses", ""), "p_lines": "",
             "coverage_gaps": "", "errors": 0, "error_msg": "",
             "count": dict(st["count"]), "ufps": {k: len(v) for k, v in st["tfps"].items()},
             "first": st["first"], "matches": st["matches"]}
        o["closest_ourpolicy"], o["closest_nearopen"] = closest(st["summaries"])
        o["distinct_summaries"] = len(st["summaries"])
        if source == "consensuses":
            o["coverage_gaps"] = ("DB consensus table: counts only (no unique fps, no loose test); "
                                  "fps per test from cons_entry (va >= 2026-09-24)")
            o["unique_fps"] = "n/a"
            o["applicable"] = ("ourpolicy_summary", "nearopen_summary")
        out.append(o)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="*")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default="net/email_history_check.csv")
    ap.add_argument("--matches", default="net/email_history_check_matches.csv")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    results = []
    jobs = sorted(a.archives, key=lambda p: -os.path.getsize(p))
    with multiprocessing.Pool(min(3, a.workers)) as pool:
        for r in pool.imap_unordered(run, jobs):
            print("done %-40s items=%-9d errors=%d %s counts=%s" % (r["archive"], r["items_scanned"], r["errors"],
                                                                  r["error_msg"], r["count"]), flush=True)
            results.append(r)
    if a.db:
        results.extend(db_rows(a.db))
        print("done DB rows", flush=True)
    results.sort(key=lambda r: (r["source"], r["month"].replace("db:", "")))
    cols = ["month", "source", "archive", "archive_bytes", "members", "unique_member_names", "items_scanned",
            "unique_fps", "n_consensuses", "p_lines", "first_time", "last_time", "unique_policy_texts"]
    for t in ALL_TESTS:
        cols += [t, t + "_fps"]
    for t in ("ourpolicy_sequence", "nearopen_sequence", "ourpolicy_summary", "nearopen_summary",
              "loose_rules_110_143_3389", "loose_summary_110_143_3389"):
        cols += ["earliest_" + t]
    cols += ["distinct_summaries", "closest_ourpolicy", "closest_nearopen", "coverage_gaps", "errors", "error_msg"]
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in results:
            row = {"month": r["month"], "source": r["source"], "archive": r["archive"],
                   "archive_bytes": r["archive_bytes"], "members": r["members"],
                   "unique_member_names": r["unique_member_names"], "items_scanned": r["items_scanned"],
                   "unique_fps": r["unique_fps"], "n_consensuses": r["n_consensuses"], "p_lines": r["p_lines"],
                   "first_time": r["tmin"], "last_time": r["tmax"], "unique_policy_texts": r["unique_policy_texts"],
                   "coverage_gaps": r["coverage_gaps"], "errors": r["errors"], "error_msg": r["error_msg"],
                   "distinct_summaries": r["distinct_summaries"], "closest_ourpolicy": r["closest_ourpolicy"],
                   "closest_nearopen": r["closest_nearopen"]}
            applicable = r.get("applicable") or (DESC_TESTS if r["source"] == "server-descriptors" else CONS_TESTS)
            for t in ALL_TESTS:
                if t in applicable:
                    row[t] = r["count"].get(t, 0)
                    row[t + "_fps"] = r["ufps"].get(t, 0)
                else:
                    row[t] = row[t + "_fps"] = "n/a"
                if "earliest_" + t in cols:
                    e = r["first"].get(t)
                    row["earliest_" + t] = ("%s %s %s %s" % e[:4]) if e else ("none" if t in applicable else "n/a")
            w.writerow([row.get(c, "") for c in cols])
    with open(a.matches, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "source", "test", "time", "fp", "nickname", "address", "detail"])
        for r in results:
            for (test, fp), e in sorted(r["matches"].items(), key=lambda kv: (kv[0][0], kv[1])):
                w.writerow([r["month"], r["source"], test, e[0], e[1], e[2], e[3], e[4]])
    print("\nEARLIEST PER TEST AND SOURCE (over all rows)")
    for source in ("server-descriptors", "consensuses"):
        for t in ALL_TESTS:
            es = [(r["first"][t], r["month"]) for r in results if r["source"] == source and t in r["first"]]
            hist = [(r["first"][t], r["month"]) for r in results
                    if r["source"] == source and t in r["first"] and not r["month"].startswith("db:")]
            print("%-19s %-28s earliest=%s | earliest in downloaded history archives=%s" % (
                source, t, min(es) if es else "none", min(hist) if hist else "none"))


if __name__ == "__main__":
    main()
