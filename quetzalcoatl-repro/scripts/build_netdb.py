#!/usr/bin/env python3
"""build_netdb.py - stream every CollecTor consensus and server-descriptor archive into one SQLite DB.

Network-wide (every relay, not only the family). Standard library only.

Usage:
  python3 -I scripts/build_netdb.py --data data --db net/netdb.sqlite [--workers 4] [--full-from "2026-09-24 00:00:00"]

One worker process per monthly archive (tarfile mode "r|xz", nothing extracted to disk); each worker
writes its own temporary SQLite file under net/tmp/, the main process merges them.

Consensus side (network-status-consensus-3, "ns" flavor)
  consensus(va, n_relays, flag counts, policy-class counts, bandwidth sums)   one row per valid-after
                                                                             (duplicates dropped)
  cons_interval(fp, start_va, end_va, n, nickname, ip, or_port, dir_port, flags, version, policy,
                bw_min, bw_max, bw_sum, after_gap, first_seen)
        presence compressed into runs of consecutive consensuses with constant
        nickname/ip/or_port/flags/version/p-line; merged across month boundaries;
        after_gap = 1 when the interval follows an absence (relative to the consensuses that exist
        in the archive, so a missing consensus hour never creates a fake absence)
  cons_descref(fp, desc_published, digest, first_va, last_va, n)
        which descriptor (r-line digest + publication time) the authorities used, and when
  cons_entry(va, fp, nickname, ip, or_port, flags, version, bw, policy, desc_published, digest)
        full per-consensus rows, only for valid-after >= --full-from (exit-weight exposure etc.)

Descriptor side
  descriptor(digest UNIQUE, fp, published, pub_epoch, nickname, address, or_port, dir_port,
             or_addresses, platform, uptime, boot_epoch, bw_avg, bw_burst, bw_obs, contact_h,
             family_h, family_n, family_cert, hibernating, ipv6_policy, ed25519, policy_h,
             policy_lines, archive)
        digest = SHA-1 of "router ..." through "router-signature\\n" (the digest the consensus
        r line refers to), so the same descriptor appearing in two monthly archives is stored once.
  policy(policy_h, text, n_lines, summary, class)      summary = re-implemented policy_summarize()
  contact(contact_h, text)
  family(family_h, fps, n)                             normalized $FP / $FP=nick / $FP~nick
"""
import argparse
import collections
import glob
import hashlib
import multiprocessing as mp
import os
import pickle
import re
import sqlite3
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (iter_tar, b64_to_hex, summarize_policy, classify_summary, ts_epoch, log,  # noqa: E402
                    NEAR_OPEN, OUR_POLICY, NONEXIT)

FLAG_COUNT = ["Exit", "BadExit", "MiddleOnly", "Guard", "Sybil", "StaleDesc", "Running", "Valid",
              "Fast", "Stable", "HSDir", "V2Dir", "Authority", "NoEdConsensus"]
PCLASSES = ["non-exit", "near-open", "OUR_POLICY", "accept-list", "other-reject-list", "none"]


# ============================================================================ consensus worker
def parse_consensus(data):
    va = None
    entries = []
    cur = None
    for raw in data.split(b"\n"):
        if not raw:
            continue
        c = raw[:2]
        if c == b"r ":
            p = raw.split(b" ")
            # r nick ident digest date time ip orport dirport
            cur = [p[1].decode("utf-8", "replace"), b64_to_hex(p[2].decode()), b64_to_hex(p[3].decode()),
                   (p[4] + b" " + p[5]).decode(), p[6].decode(), int(p[7]), int(p[8]),
                   "", "", 0, "", ""]  # 7 flags, 8 version, 9 bw, 10 policy, 11 a-line
            entries.append(cur)
        elif cur is not None and c == b"s ":
            cur[7] = " ".join(sorted(raw[2:].decode().split()))
        elif cur is not None and c == b"v ":
            cur[8] = raw[2:].decode().strip()
        elif cur is not None and c == b"w ":
            m = re.search(rb"Bandwidth=(\d+)", raw)
            cur[9] = int(m.group(1)) if m else 0
        elif cur is not None and c == b"p ":
            cur[10] = raw[2:].decode().strip()
        elif cur is not None and c == b"a ":
            cur[11] = (cur[11] + " " if cur[11] else "") + raw[2:].decode().strip()
        elif raw.startswith(b"valid-after "):
            va = raw[12:].decode().strip()
        elif raw.startswith(b"directory-footer"):
            break
    return va, entries


def consensus_worker(args):
    path, tmpdir, full_from = args
    name = os.path.basename(path)
    final = os.path.join(tmpdir, name + ".sqlite")
    out = final + ".part"
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript("""
      CREATE TABLE consensus(va TEXT PRIMARY KEY, member TEXT, n INTEGER, counts TEXT);
      CREATE TABLE iv(fp TEXT, start_va TEXT, end_va TEXT, n INTEGER, nickname TEXT, ip TEXT,
                      or_port INTEGER, dir_port INTEGER, flags TEXT, version TEXT, policy TEXT,
                      bw_min INTEGER, bw_max INTEGER, bw_sum INTEGER, a_line TEXT);
      CREATE TABLE dref(fp TEXT, desc_published TEXT, digest TEXT, first_va TEXT, last_va TEXT, n INTEGER);
      CREATE TABLE entry(va TEXT, fp TEXT, nickname TEXT, ip TEXT, or_port INTEGER, flags TEXT,
                         version TEXT, bw INTEGER, policy TEXT, desc_published TEXT, digest TEXT);
    """)
    month = {}
    for mname, data in iter_tar(path):
        va, entries = parse_consensus(data)
        if not va:
            continue
        if va in month:
            continue  # duplicate valid-after
        # keep each parsed consensus compressed until all are read (archive order is not va order)
        month[va] = (mname, zlib.compress(pickle.dumps(entries, protocol=4), 1))
    vas = sorted(month)
    state = {}
    closed = []
    dref = {}
    prev_va = None
    for va in vas:
        mname, blob = month.pop(va)
        entries = pickle.loads(zlib.decompress(blob))
        cnt = collections.Counter()
        for e in entries:
            nick, fp, dig, dpub, ip, orp, dirp, flags, ver, bw, pol, aline = e
            fl = set(flags.split())
            cnt["n"] += 1
            for f in FLAG_COUNT:
                if f in fl:
                    cnt[f] += 1
            pc = classify_summary(pol)
            cnt["pol:" + pc] += 1
            cnt["bw_total"] += bw
            if "Exit" in fl:
                cnt["bw_exitflag"] += bw
                if "BadExit" not in fl:
                    cnt["bw_exit_usable"] += bw
            if "BadExit" in fl:
                cnt["bw_badexit"] += bw
            if pc in ("near-open", "OUR_POLICY"):
                cnt["bw_attackerpol"] += bw
                if "Exit" in fl:
                    cnt["n_attackerpol_exitflag"] += 1
                    if "BadExit" not in fl:
                        cnt["n_attackerpol_usable_exit"] += 1
                        cnt["bw_attackerpol_usable_exit"] += bw
            if pol != NONEXIT:
                cnt["n_policy_exit"] += 1
            key = (nick, ip, orp, flags, ver, pol)
            st = state.get(fp)
            if st is not None and st["key"] == key and st["end"] == prev_va:
                st["end"] = va
                st["n"] += 1
                st["bw_min"] = min(st["bw_min"], bw)
                st["bw_max"] = max(st["bw_max"], bw)
                st["bw_sum"] += bw
                st["a"] = aline or st["a"]
            else:
                if st is not None:
                    closed.append(st)
                state[fp] = {"fp": fp, "start": va, "end": va, "n": 1, "key": key, "dirp": dirp,
                             "bw_min": bw, "bw_max": bw, "bw_sum": bw, "a": aline}
            dk = (fp, dpub, dig)
            d = dref.get(dk)
            if d is None:
                dref[dk] = [va, va, 1]
            else:
                d[1] = va
                d[2] += 1
            if va >= full_from:
                db.execute("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (va, fp, nick, ip, orp, flags, ver, bw, pol, dpub, dig))
        db.execute("INSERT INTO consensus VALUES (?,?,?,?)",
                   (va, mname, cnt["n"], repr(dict(cnt))))
        prev_va = va
        if len(closed) > 50000:
            _flush_iv(db, closed)
            closed = []
    closed.extend(state.values())
    _flush_iv(db, closed)
    db.executemany("INSERT INTO dref VALUES (?,?,?,?,?,?)",
                   [(k[0], k[1], k[2], v[0], v[1], v[2]) for k, v in dref.items()])
    db.commit()
    db.close()
    os.replace(out, final)
    return name, len(vas)


def _flush_iv(db, rows):
    db.executemany("INSERT INTO iv VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [(s["fp"], s["start"], s["end"], s["n"], s["key"][0], s["key"][1], s["key"][2],
                     s["dirp"], s["key"][3], s["key"][4], s["key"][5], s["bw_min"], s["bw_max"],
                     s["bw_sum"], s["a"]) for s in rows])


# ============================================================================ descriptor worker
def norm_family_token(tok):
    t = tok.lstrip("$").split("=")[0].split("~")[0].upper()
    return t if re.fullmatch(r"[0-9A-F]{40}", t) else None


def parse_descriptor(data):
    d = {"policy": [], "family": None, "family_cert": 0, "or_addresses": []}
    in_pem = False
    for raw in data.split(b"\n"):
        line = raw.decode("utf-8", "replace").rstrip("\r")
        if line.startswith("-----BEGIN"):
            in_pem = True
            continue
        if line.startswith("-----END"):
            in_pem = False
            continue
        if in_pem:
            continue
        sp = line.find(" ")
        kw = line if sp < 0 else line[:sp]
        val = "" if sp < 0 else line[sp + 1:].strip()
        if kw == "router":
            p = val.split()
            d["nickname"] = p[0] if p else ""
            d["address"] = p[1] if len(p) > 1 else ""
            d["or_port"] = int(p[2]) if len(p) > 2 and p[2].isdigit() else None
            d["dir_port"] = int(p[4]) if len(p) > 4 and p[4].isdigit() else None
        elif kw == "published":
            d["published"] = val
        elif kw == "fingerprint":
            d["fingerprint"] = val.replace(" ", "").upper()
        elif kw == "platform":
            d["platform"] = val
        elif kw == "uptime":
            d["uptime"] = int(val) if val.isdigit() else None
        elif kw == "bandwidth":
            p = val.split()
            d["bw"] = [int(x) if x.isdigit() else None for x in (p + [None, None, None])[:3]]
        elif kw == "contact":
            d["contact"] = val
        elif kw == "family":
            d["family"] = val.split()
        elif kw == "family-cert":
            d["family_cert"] += 1
        elif kw == "hibernating":
            d["hibernating"] = val
        elif kw == "ipv6-policy":
            d["ipv6_policy"] = val
        elif kw == "or-address":
            d["or_addresses"].append(val)
        elif kw == "master-key-ed25519":
            d["ed25519"] = val
        elif kw == "accept" or kw == "reject":
            d["policy"].append(line.strip())
    return d


def desc_digest(data):
    s = data.find(b"router ")
    while s > 0 and data[s - 1:s] != b"\n":
        s = data.find(b"router ", s + 1)
    e = data.find(b"\nrouter-signature\n")
    if s < 0 or e < 0:
        return None
    return hashlib.sha1(data[s:e + len(b"\nrouter-signature\n")]).hexdigest().upper()


def descriptor_worker(args):
    path, tmpdir = args
    name = os.path.basename(path)
    final = os.path.join(tmpdir, name + ".sqlite")
    out = final + ".part"
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript("""
      CREATE TABLE descriptor(digest TEXT, fp TEXT, published TEXT, pub_epoch INTEGER, nickname TEXT,
        address TEXT, or_port INTEGER, dir_port INTEGER, or_addresses TEXT, platform TEXT, uptime INTEGER,
        boot_epoch INTEGER, bw_avg INTEGER, bw_burst INTEGER, bw_obs INTEGER, contact_h TEXT,
        family_h TEXT, family_n INTEGER, family_cert INTEGER, hibernating TEXT, ipv6_policy TEXT,
        ed25519 TEXT, policy_h TEXT, policy_lines INTEGER, archive TEXT);
      CREATE TABLE policy(policy_h TEXT PRIMARY KEY, text TEXT, n_lines INTEGER, summary TEXT, class TEXT);
      CREATE TABLE contact(contact_h TEXT PRIMARY KEY, text TEXT);
      CREATE TABLE family(family_h TEXT PRIMARY KEY, fps TEXT, n INTEGER);
    """)
    pols, cons, fams = {}, {}, {}
    batch = []
    n = 0
    for _, data in iter_tar(path):
        n += 1
        dig = desc_digest(data)
        d = parse_descriptor(data)
        if "published" not in d or "fingerprint" not in d:
            continue
        ptext = "\n".join(d["policy"])
        ph = hashlib.sha1(ptext.encode()).hexdigest()
        if ph not in pols:
            s = summarize_policy(d["policy"])
            pols[ph] = (ptext, len(d["policy"]), s, classify_summary(s))
        contact = d.get("contact")
        ch = hashlib.sha1(contact.encode()).hexdigest()[:16] if contact is not None else "-"
        if contact is not None and ch not in cons:
            cons[ch] = contact
        if d["family"] is None:
            fh, fn = "-", 0
        else:
            fps = sorted({x for x in (norm_family_token(t) for t in d["family"]) if x})
            ftext = " ".join(fps)
            fh = hashlib.sha1(ftext.encode()).hexdigest()[:16]
            fn = len(fps)
            if fh not in fams:
                fams[fh] = (ftext, fn)
        try:
            pe = ts_epoch(d["published"])
        except ValueError:
            continue
        up = d.get("uptime")
        bw = d.get("bw", [None, None, None])
        batch.append((dig or ("NODIGEST-" + hashlib.sha1(data).hexdigest().upper()), d["fingerprint"],
                      d["published"], pe, d.get("nickname"), d.get("address"), d.get("or_port"),
                      d.get("dir_port"), " ".join(d["or_addresses"]), d.get("platform"), up,
                      (pe - up) if up is not None else None, bw[0], bw[1], bw[2], ch, fh, fn,
                      d["family_cert"], d.get("hibernating"), d.get("ipv6_policy"), d.get("ed25519"),
                      ph, len(d["policy"]), name))
        if len(batch) >= 20000:
            db.executemany("INSERT INTO descriptor VALUES (%s)" % ",".join("?" * 25), batch)
            batch = []
    if batch:
        db.executemany("INSERT INTO descriptor VALUES (%s)" % ",".join("?" * 25), batch)
    db.executemany("INSERT INTO policy VALUES (?,?,?,?,?)", [(k,) + v for k, v in pols.items()])
    db.executemany("INSERT INTO contact VALUES (?,?)", list(cons.items()))
    db.executemany("INSERT INTO family VALUES (?,?,?)", [(k,) + v for k, v in fams.items()])
    db.commit()
    db.close()
    os.replace(out, final)
    return name, n


def run_worker(job):
    kind, args = job
    if kind == "cons":
        return ("cons",) + consensus_worker(args)
    return ("desc",) + descriptor_worker(args)


# ============================================================================ merge
def merge(dbpath, tmpdir, cons_names, desc_names):
    if os.path.exists(dbpath):
        os.remove(dbpath)
    db = sqlite3.connect(dbpath)
    db.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE consensus(va TEXT PRIMARY KEY, member TEXT, n INTEGER, counts TEXT);
      CREATE TABLE cons_interval(fp TEXT, start_va TEXT, end_va TEXT, n INTEGER, nickname TEXT, ip TEXT,
        or_port INTEGER, dir_port INTEGER, flags TEXT, version TEXT, policy TEXT, bw_min INTEGER,
        bw_max INTEGER, bw_sum INTEGER, a_line TEXT, after_gap INTEGER, first_seen INTEGER);
      CREATE TABLE cons_descref(fp TEXT, desc_published TEXT, digest TEXT, first_va TEXT, last_va TEXT,
        n INTEGER);
      CREATE TABLE cons_entry(va TEXT, fp TEXT, nickname TEXT, ip TEXT, or_port INTEGER, flags TEXT,
        version TEXT, bw INTEGER, policy TEXT, desc_published TEXT, digest TEXT);
      CREATE TABLE descriptor(digest TEXT PRIMARY KEY, fp TEXT, published TEXT, pub_epoch INTEGER,
        nickname TEXT, address TEXT, or_port INTEGER, dir_port INTEGER, or_addresses TEXT, platform TEXT,
        uptime INTEGER, boot_epoch INTEGER, bw_avg INTEGER, bw_burst INTEGER, bw_obs INTEGER,
        contact_h TEXT, family_h TEXT, family_n INTEGER, family_cert INTEGER, hibernating TEXT,
        ipv6_policy TEXT, ed25519 TEXT, policy_h TEXT, policy_lines INTEGER, archive TEXT);
      CREATE TABLE policy(policy_h TEXT PRIMARY KEY, text TEXT, n_lines INTEGER, summary TEXT, class TEXT);
      CREATE TABLE contact(contact_h TEXT PRIMARY KEY, text TEXT);
      CREATE TABLE family(family_h TEXT PRIMARY KEY, fps TEXT, n INTEGER);
      CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    # ---- consensuses: global ordered valid-after list
    vas = []
    for nm in cons_names:
        t = sqlite3.connect(os.path.join(tmpdir, nm + ".sqlite"))
        rows = t.execute("SELECT va, member, n, counts FROM consensus ORDER BY va").fetchall()
        for r in rows:
            if vas and r[0] == vas[-1]:
                continue
            vas.append(r[0])
            db.execute("INSERT OR IGNORE INTO consensus VALUES (?,?,?,?)", r)
        t.close()
    vas = sorted(set(vas))
    pred = {vas[i]: (vas[i - 1] if i else None) for i in range(len(vas))}
    # ---- intervals: merge across month boundaries, compute after_gap / first_seen
    pending = {}   # fp -> last interval (list), not yet written
    seen = set()
    out = []

    def flush():
        db.executemany("INSERT INTO cons_interval VALUES (%s)" % ",".join("?" * 17), out)
        out.clear()

    for nm in cons_names:
        t = sqlite3.connect(os.path.join(tmpdir, nm + ".sqlite"))
        for r in t.execute("SELECT * FROM iv ORDER BY fp, start_va"):
            (fp, s, e, n, nick, ip, orp, dirp, flags, ver, pol, bmin, bmax, bsum, aline) = r
            last = pending.get(fp)
            key = (nick, ip, orp, flags, ver, pol)
            if last is not None and tuple(last[4:7]) + (last[8], last[9], last[10]) == key \
                    and last[2] == pred[s]:
                last[2] = e
                last[3] += n
                last[11] = min(last[11], bmin)
                last[12] = max(last[12], bmax)
                last[13] += bsum
                last[14] = aline or last[14]
                continue
            if last is not None:
                out.append(tuple(last))
            after_gap = 1 if (last is not None and last[2] != pred[s]) else 0
            first_seen = 0 if fp in seen else 1
            seen.add(fp)
            pending[fp] = [fp, s, e, n, nick, ip, orp, dirp, flags, ver, pol, bmin, bmax, bsum, aline,
                           after_gap, first_seen]
            if len(out) > 100000:
                flush()
        t.close()
    out.extend(tuple(v) for v in pending.values())
    flush()
    # ---- descriptor references: merge
    dref = {}
    for nm in cons_names:
        t = sqlite3.connect(os.path.join(tmpdir, nm + ".sqlite"))
        for fp, dp, dg, f, l, n in t.execute("SELECT * FROM dref"):
            k = (fp, dp, dg)
            if k in dref:
                o = dref[k]
                dref[k] = [min(o[0], f), max(o[1], l), o[2] + n]
            else:
                dref[k] = [f, l, n]
        db.execute("ATTACH ? AS t", (os.path.join(tmpdir, nm + ".sqlite"),))
        db.execute("INSERT INTO cons_entry SELECT * FROM t.entry")
        db.commit()
        db.execute("DETACH t")
        t.close()
    db.executemany("INSERT INTO cons_descref VALUES (?,?,?,?,?,?)",
                   [k + tuple(v) for k, v in dref.items()])
    db.commit()
    # ---- descriptors
    for nm in desc_names:
        db.execute("ATTACH ? AS t", (os.path.join(tmpdir, nm + ".sqlite"),))
        db.execute("INSERT OR IGNORE INTO descriptor SELECT * FROM t.descriptor")
        db.execute("INSERT OR IGNORE INTO policy SELECT * FROM t.policy")
        db.execute("INSERT OR IGNORE INTO contact SELECT * FROM t.contact")
        db.execute("INSERT OR IGNORE INTO family SELECT * FROM t.family")
        db.commit()
        db.execute("DETACH t")
    db.execute("INSERT INTO meta VALUES ('first_va', ?)", (vas[0],))
    db.execute("INSERT INTO meta VALUES ('last_va', ?)", (vas[-1],))
    db.execute("INSERT INTO meta VALUES ('n_consensuses', ?)", (str(len(vas)),))
    log("indexing")
    db.executescript("""
      CREATE INDEX iv_fp ON cons_interval(fp, start_va);
      CREATE INDEX iv_start ON cons_interval(start_va);
      CREATE INDEX iv_end ON cons_interval(end_va);
      CREATE INDEX ce_va ON cons_entry(va);
      CREATE INDEX ce_fp ON cons_entry(fp, va);
      CREATE INDEX dr_fp ON cons_descref(fp, desc_published);
      CREATE INDEX dr_dig ON cons_descref(digest);
      CREATE INDEX d_fp ON descriptor(fp, pub_epoch);
      CREATE INDEX d_pub ON descriptor(pub_epoch);
      CREATE INDEX d_pol ON descriptor(policy_h);
      CREATE INDEX d_addr ON descriptor(address);
      CREATE INDEX d_contact ON descriptor(contact_h);
    """)
    db.commit()
    db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--full-from", default="2026-09-24 00:00:00")
    ap.add_argument("--merge-only", action="store_true")
    args = ap.parse_args()
    tmpdir = os.path.join(os.path.dirname(args.db) or ".", "tmp")
    os.makedirs(tmpdir, exist_ok=True)
    cons = sorted(glob.glob(os.path.join(args.data, "consensuses-*.tar.xz")))
    desc = sorted(glob.glob(os.path.join(args.data, "server-descriptors-*.tar.xz")))
    if not args.merge_only:
        # biggest jobs first
        jobs = [("desc", (p, tmpdir)) for p in desc] + [("cons", (p, tmpdir, args.full_from)) for p in cons]
        # resume: skip archives whose worker output is complete (written via .part + rename)
        jobs = [j for j in jobs if not os.path.exists(os.path.join(tmpdir, os.path.basename(j[1][0]) + ".sqlite"))]
        log("jobs to run:", [os.path.basename(j[1][0]) for j in jobs])
        with mp.Pool(args.workers) as pool:
            for res in pool.imap_unordered(run_worker, jobs):
                log("finished", res)
    log("merging")
    merge(args.db, tmpdir, [os.path.basename(p) for p in cons], [os.path.basename(p) for p in desc])
    log("done", args.db)


if __name__ == "__main__":
    main()
